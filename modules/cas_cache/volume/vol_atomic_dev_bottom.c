/*
* Copyright(c) 2012-2021 Intel Corporation
* SPDX-License-Identifier: BSD-3-Clause-Clear
*/

#include "cas_cache.h"
#include "utils/utils_mpool.h"
#if defined(CAS_NVME_FULL)

#include <linux/nvme.h>
#include <linux/blk-mq.h>

#define CAS_DEBUG_IO_ATOMIC 0

#if 1 == CAS_DEBUG_IO_ATOMIC
#define CAS_DEBUG_TRACE() printk(KERN_DEBUG \
		"[IO][ATOMIC] %s:%d\n", __func__, __LINE__)

#define CAS_DEBUG_MSG(msg) printk(KERN_DEBUG \
		"[IO][ATOMIC] %s:%d - %s\n", __func__, __LINE__, msg)

#define CAS_DEBUG_PARAM(format, ...) printk(KERN_DEBUG \
		"[IO][ATOMIC] %s:%d - "format"\n", __func__, \
		__LINE__, ##__VA_ARGS__)
#else
#define CAS_DEBUG_TRACE()
#define CAS_DEBUG_MSG(msg)
#define CAS_DEBUG_PARAM(format, ...)
#endif

#define ADMIN_TIMEOUT			(60 * HZ)

struct cas_atomic_io {
	ocf_volume_t volume;

	struct cas_atomic_io *master;
	atomic_t req_remaining;
	uint32_t count;

	uint64_t addr;
	uint32_t bytes;
	uint32_t start;
	uint32_t end;

	int error;
	unsigned dir:1;
	unsigned metadata:1;
	unsigned discard:1;
	unsigned long flags;

	ocf_end_io_t cmpl_fn;
	void *cmpl_context;

	struct blk_data *data;
	uint32_t bvec_size;

	struct nvme_command cmd;
	struct bio *bio;
	struct request *request;

	struct bio_vec_iter iter;
};

static struct env_mpool *atomic_io_allocator;

static inline uint32_t cas_atomic_max_io_sectors(void)
{
	/* TODO Take into account max IO size of bottom device */
	return 128 * KiB / (SECTOR_SIZE + OCF_ATOMIC_METADATA_SIZE);
}

static inline uint32_t cas_atomic_size_of(uint32_t size)
{
	BUG_ON(size % SECTOR_SIZE);
	return size + (size / SECTOR_SIZE * OCF_ATOMIC_METADATA_SIZE);
}

static void cas_atomic_dealloc(struct cas_atomic_io *atomics)
{
	uint32_t i;

	for (i = 0; i < atomics->count; i++) {
		struct cas_atomic_io *this = &atomics[i];

		if (this->request && !IS_ERR(this->request)) {
			blk_mq_free_request(this->request);
			this->request = NULL;
		}

		if (this->bio)
			bio_put(this->bio);

		if (this->data) {
			cas_ctx_data_secure_erase(this->data);
			cas_ctx_data_free(this->data);
		}
	}

	env_mpool_del(atomic_io_allocator, atomics, atomics->count);
}

static struct cas_atomic_io *cas_atomic_alloc(int dir, struct ocf_io *io, bool write_zero)
{
	/* Get max size of IO */
	const uint32_t max_io_size = cas_atomic_max_io_sectors()
			* SECTOR_SIZE;

	/* Get number of IOs to be issued */
	uint32_t ios_count;
	ocf_cache_t cache = ocf_volume_get_cache(ocf_io_get_volume(io));

	uint64_t addr = io->addr;
	uint32_t i, bytes = io->bytes;
	uint32_t increase_sectors_start = 0, increase_sectors_end = 0;
	struct cas_atomic_io *atoms;

	if (dir == OCF_WRITE && !write_zero) {
		/* TODO: this logic is probably no longer required */
		BUG_ON(!cache);
		increase_sectors_start =
				ocf_metadata_check_invalid_before(cache, addr);

		increase_sectors_end =
				ocf_metadata_check_invalid_after(cache, addr,
						io->bytes);
		increase_sectors_start *= 512;
		increase_sectors_end *= 512;

		if (increase_sectors_start) {
			bytes += increase_sectors_start;
			addr -= increase_sectors_start;
		}

		if (increase_sectors_end)
			bytes += increase_sectors_end;
	}

	/* Get number of IOs to be issued */
	ios_count = DIV_ROUND_UP(bytes, max_io_size);

	atoms = env_mpool_new(atomic_io_allocator,
			ios_count);
	if (!atoms)
		return NULL;

	CAS_DEBUG_PARAM("Addr = %llu, bytes = %u", io->addr, io->bytes);

	/* setup master IO */
	atomic_set(&atoms->req_remaining, ios_count);

	atoms->count = ios_count;
	atoms->cmpl_fn = io->end;
	atoms->cmpl_context = io;

	for (i = 0; i < ios_count; i++) {
		struct cas_atomic_io *this = &atoms[i];

		this->master = atoms;
		this->addr = addr;
		this->bytes = min(bytes, max_io_size);
		this->dir = dir;
		this->flags = io->flags;
		this->volume = ocf_io_get_volume(io);

		CAS_DEBUG_PARAM("Sub-atomic IO (%u), Addr = %llu, bytes = %u",
				i, this->addr, this->bytes);

		addr += this->bytes;
		bytes -= this->bytes;

		/* Allocate BIO data vector with pages */
		this->bvec_size = cas_atomic_size_of(this->bytes);
		this->bvec_size = DIV_ROUND_UP(this->bvec_size, PAGE_SIZE);

		if (write_zero || increase_sectors_start ||
				increase_sectors_end)
			this->data = cas_ctx_data_zalloc(this->bvec_size);
		else
			this->data = cas_ctx_data_alloc(this->bvec_size);

		if (!this->data)
			goto cas_atomic_alloc_ERROR;

		/* Set length of last page */
		this->data->vec[this->bvec_size - 1].bv_len =
			cas_atomic_size_of(this->bytes) % PAGE_SIZE;

		CAS_DEBUG_PARAM("Sub-atomic IO (%u), BIO vector size = %u, "
				"alignment %u", i, this->bvec_size,
				this->data->vec[this->bvec_size - 1].bv_len);

		this->start = min(this->bytes, increase_sectors_start);
		increase_sectors_start -= this->start;
	}
	BUG_ON(bytes);

	for (i = ios_count; i && increase_sectors_end; i--) {
		struct cas_atomic_io *this = &atoms[i - 1];

		this->end = min(this->bytes, increase_sectors_end);
		increase_sectors_end -= this->end;
	}

	return atoms;

cas_atomic_alloc_ERROR:

	if (atoms)
		cas_atomic_dealloc(atoms);

	return NULL;
}

static int cas_atomic_rd_complete(struct cas_atomic_io *atom)
{
	struct bio_vec_iter *dst, src;
	uint32_t copied;
	const uint32_t size = OCF_ATOMIC_METADATA_SIZE;

	uint32_t bytes = atom->bytes;

	CAS_DEBUG_TRACE();

	/* Initialize iterators */
	cas_io_iter_init(&src, atom->data->vec, atom->bvec_size);
	dst = &atom->iter;

	BUG_ON(bytes % SECTOR_SIZE);
	BUG_ON(size != OCF_ATOMIC_METADATA_SIZE);

	copied = 0;
	while (bytes) {
		/* Copy data */
		copied += cas_io_iter_cpy(dst, &src, SECTOR_SIZE);

		/* Omit metadata */
		copied += cas_io_iter_move(&src, size);

		bytes -= SECTOR_SIZE;
	}

	/* Validate if copied proper numbers of bytes */
	if (copied != cas_atomic_size_of(atom->bytes)) {
		CAS_DEBUG_PARAM("ERROR, copied %u, expected = %u",
				copied, cas_atomic_size_of(atom->bytes));
		/* Metadata and data coping problem */
		return -EIO;
	}

	return 0;
}

static int cas_atomic_rd_metadata_complete(struct cas_atomic_io *atom)
{
	struct bio_vec_iter *dst, src;
	uint32_t copied;
	const uint32_t size = OCF_ATOMIC_METADATA_SIZE;

	uint32_t bytes = atom->bytes;

	CAS_DEBUG_TRACE();

	/* Initialize iterators */
	cas_io_iter_init(&src, atom->data->vec, atom->bvec_size);
	dst = &atom->iter;

	BUG_ON(bytes % SECTOR_SIZE);
	BUG_ON(size != OCF_ATOMIC_METADATA_SIZE);

	copied = 0;
	while (bytes) {
		/* Copy data */
		copied += cas_io_iter_move(&src, SECTOR_SIZE);

		/* Omit metadata */
		copied += cas_io_iter_cpy(dst, &src, size);

		bytes -= SECTOR_SIZE;
	}

	/* Validate if copied proper numbers of bytes */
	if (copied != cas_atomic_size_of(atom->bytes)) {
		CAS_DEBUG_PARAM("ERROR, copied %u, expected = %u",
				copied, cas_atomic_size_of(atom->bytes));
		/* Metadata and data coping problem */
		return -EIO;
	}

	return 0;
}

static int cas_atomic_rd_prepare(struct ocf_io *io,
		struct cas_atomic_io *atom)
{
	struct blkio *blkio = cas_io_to_blkio(io);
	uint32_t moved;

	/* Store BIO vector iterator, when read completed then it will be
	 * known were place data
	 */
	cas_io_iter_copy_set(&atom->iter, &blkio->iter);

	/* Move iterator for next IO */
	moved = cas_io_iter_move(&blkio->iter, atom->bytes);

	/* Validate if there is enough space in BIO data vector to do read */
	if (moved != atom->bytes) {
		CAS_DEBUG_PARAM("ERROR, moved %u, expected = %u",
			moved, cas_atomic_size_of(atom->bytes));
		return -EINVAL;
	}

	return 0;
}

static int cas_atomic_wr_prepare(struct ocf_io *io,
		struct cas_atomic_io *atom)
{
	struct blkio *blkio = cas_io_to_blkio(io);
	ocf_cache_t cache;
	struct ocf_atomic_metadata metadata;
	struct bio_vec_iter dst, src;
	uint32_t copied, added;

	uint64_t addr = atom->addr;
	uint32_t bytes = atom->bytes;

	cache = ocf_volume_get_cache(ocf_io_get_volume(io));

	/* Initialize iterators */
	cas_io_iter_init(&dst, atom->data->vec, atom->bvec_size);
	cas_io_iter_copy_set(&src, &blkio->iter);

	BUG_ON(!cache);
	BUG_ON(bytes % SECTOR_SIZE);

	copied = 0;
	if (atom->start) {
		added = cas_atomic_size_of(atom->start);
		cas_io_iter_move(&dst, added);

		bytes -= atom->start;
		copied = added;

		addr += atom->start;
	}

	if (atom->end) {
		added = cas_atomic_size_of(atom->end);
		bytes -= atom->end;
		copied += added;
	}

	BUG_ON(sizeof(metadata) != OCF_ATOMIC_METADATA_SIZE);

	while (bytes) {
		/* Get metadata */
		if (ocf_metadata_get_atomic_entry(cache, addr, &metadata))
			break;

		/* Copy data */
		copied += cas_io_iter_cpy(&dst, &src, SECTOR_SIZE);

		/* Copy metadata */
		copied += cas_io_iter_cpy_from_data(&dst, &metadata,
				sizeof(metadata));

		bytes -= SECTOR_SIZE;
		addr += SECTOR_SIZE;
	}

	cas_io_iter_move(&blkio->iter, atom->bytes - (atom->start + atom->end));

	/* Validate if copied proper numbers of bytes */
	if (copied != cas_atomic_size_of(atom->bytes)) {
		CAS_DEBUG_PARAM("ERROR, copied %u, expected = %u",
				copied, cas_atomic_size_of(atom->bytes));
		/* Metadata and data coping problem */
		return -EINVAL;
	}

	return 0;
}

static int cas_atomic_rd_metadata_prepare(struct ocf_io *io,
		struct cas_atomic_io *atom)
{
	struct blkio *blkio = cas_io_to_blkio(io);
	uint32_t moved;

	BUG_ON(io->dir != OCF_READ);

	atom->metadata = true;

	/* Store BIO vector iterator, when read completed then it will be
	 * known were place data
	 */
	cas_io_iter_copy_set(&atom->iter, &blkio->iter);

	/* Move iterator for next IO */
	moved = cas_io_iter_move(&blkio->iter, (atom->bytes / SECTOR_SIZE) *
		OCF_ATOMIC_METADATA_SIZE);

	/* Validate if copied proper numbers of bytes */
	if (moved != (atom->bytes / SECTOR_SIZE) *
		OCF_ATOMIC_METADATA_SIZE) {
		CAS_DEBUG_PARAM("ERROR, copied %u, expected = %u",
				moved, cas_atomic_size_of(atom->bytes));
		/* Metadata and data coping problem */
		return -EIO;
	}

	return 0;
}

static void cas_atomic_end_atom(struct cas_atomic_io *atom, int error)
{
	struct cas_atomic_io *master = atom->master;
	struct ocf_io *io = master->cmpl_context;

	if (error)
		master->error |= error;

	if (atomic_dec_return(&master->req_remaining))
		return;

	CAS_DEBUG_MSG("Completion");

	/* Send completion to caller */
	master->cmpl_fn(io, master->error);

	/* Free allocated structures */
	cas_atomic_dealloc(master);
	ocf_io_put(io);
}

static CAS_DECLARE_BLOCK_CALLBACK(cas_atomic_fire_atom, struct bio *bio,
		unsigned int bytes, int error)
{
	int err;
	struct cas_atomic_io *atom;
	struct bd_object *bdobj;

	BUG_ON(!bio);
	BUG_ON(!bio->bi_private);
	err = CAS_BLOCK_CALLBACK_ERROR(bio, error);
	atom = bio->bi_private;
	BUG_ON(!atom->master);
	bdobj = bd_object(atom->volume);

	CAS_DEBUG_PARAM("BIO result = %d", CAS_BLOCK_CALLBACK_ERROR(bio, error));

	if (err != 0)
		goto out;

	if (atom->discard)
		goto out;

	if (atom->metadata) {
		if (cas_atomic_rd_metadata_complete(atom))
			atom->master->error = -EIO;
		goto out;
	}

	if (atom->dir == OCF_READ && cas_atomic_rd_complete(atom))
		atom->master->error = -EIO;

out:
	/* Free BIO, no needed any more */
	BUG_ON(bio != atom->bio);
	bio_put(bio);
	atom->bio = NULL;

	cas_atomic_end_atom(atom, err);
}

static void _cas_atomic_setup_cmd(
	ocf_volume_t volume,
	struct request *req,
	struct bio* bio,
	uint64_t bytes,
	int dir,
	void *end_io_data,
	struct nvme_command *cmd)
{
	struct bd_object *bdobj = bd_object(volume);
	unsigned int ns_id = bdobj->atomic_params.nsid;
	unsigned long *cmd_addr = blk_mq_rq_to_pdu(req);

	cmd->rw.opcode = (dir == OCF_WRITE) ? nvme_cmd_write : nvme_cmd_read;
	cmd->rw.nsid = cpu_to_le32(ns_id);
	cmd->rw.slba = cpu_to_le64(CAS_BIO_BISECTOR(bio));
	cmd->rw.length = cpu_to_le16((bytes / SECTOR_SIZE) - 1);
	cmd->rw.control = cpu_to_le16(NVME_RW_LR);

	req->cmd_type = REQ_TYPE_DRV_PRIV;
	req->cmd_flags |= REQ_FAILFAST_DRIVER;

	*cmd_addr = (unsigned long)cmd;

	req->timeout = ADMIN_TIMEOUT; /* TODO Use timeout for regular IO */

	req->cmd = (unsigned char *) cmd;
	req->cmd_len = sizeof(*cmd);
	req->special = NULL;
	req->end_io_data = end_io_data;
}

static void cas_atomic_setup_cmd(int dir, struct cas_atomic_io *atom)
{
	_cas_atomic_setup_cmd(atom->volume, atom->request, atom->bio,
		atom->bytes, dir, atom, &atom->cmd);
}

static void cas_atomic_end_request(struct request *request, int error)
{
	struct cas_atomic_io *atom;

	BUG_ON(!request);
	atom = request->end_io_data;

	/* Free request not needed any more */
	BUG_ON(atom->request != request);
	blk_mq_free_request(request);
	atom->request = NULL;

	CAS_DEBUG_PARAM("RQ result = %d", error);

	cas_atomic_end_atom(atom, error);
}

static void cas_atomic_fire_atom(int dir, struct ocf_io *io,
		struct cas_atomic_io *atom)
{
	struct bd_object *bdobj = bd_object(atom->volume);
	struct block_device *bdev = bdobj->btm_bd;
	struct request_queue *queue = bdev_get_queue(bdev);

	struct bio *bio;
	struct bio_vec *bvec;
	uint32_t i;

	/* Allocate BIO */
	bio = atom->bio = bio_alloc(GFP_NOIO, atom->bvec_size);
	if (!bio)
		goto _fire_atom_ERROR;

	/* Setup BIO */
	bio->bi_bdev = bdev;
	CAS_BIO_BISECTOR(bio) = atom->addr / SECTOR_SIZE;
	bio->bi_next = NULL;
	bio->bi_private = atom;
	CAS_BIO_OP_FLAGS(bio) |= io->flags;
	bio->bi_end_io = CAS_REFER_BLOCK_CALLBACK(cas_atomic_fire_atom);

	/* Add pages to the BIO */
	bvec = atom->data->vec;
	for (i = 0; i < atom->bvec_size; i++, bvec++) {
		int added = bio_add_pc_page(queue, bio,
			bvec->bv_page, bvec->bv_len, bvec->bv_offset);

		if (added != bvec->bv_len) {
			/* Oops, a problem, cannot add page to the BIO */
			goto _fire_atom_ERROR;
		}
	}

	/* Allocate request */
	atom->request = cas_blk_make_request(queue, atom->bio, GFP_NOIO);
	if (IS_ERR(atom->request)) {
		atom->request = NULL;
		goto _fire_atom_ERROR;
	}

	/* Setup command */
	cas_atomic_setup_cmd(dir, atom);

	/* Additional completion for request */
	atomic_inc(&atom->master->req_remaining);

	/* Send requests (NVME atomic command) */
	blk_execute_rq_nowait(queue, NULL, atom->request, 0,
			cas_atomic_end_request);

	return;

_fire_atom_ERROR:
	CAS_DEBUG_MSG("ERROR");
	cas_atomic_end_atom(atom, -EIO);
}

static void cas_atomic_fire_atoms(int dir, struct ocf_io *io,
		struct cas_atomic_io *atoms)
{
	uint32_t i;

	ocf_io_get(io);

	for (i = 0; i < atoms->count; i++) {
		struct cas_atomic_io *this = &atoms[i];

		CAS_DEBUG_PARAM("Fire(%u), Addr = %llu, bytes = %u",
				i, this->addr, this->bytes);
		cas_atomic_fire_atom(dir, io, this);
	}
}

typedef int (*cas_prepare_atom_pfn_t)(struct ocf_io *io,
		struct cas_atomic_io *atoms);

static int cas_atomic_prepare_atoms(struct ocf_io *io,
	cas_prepare_atom_pfn_t prepare,
	struct cas_atomic_io *atoms)
{
	int i;
	int result = 0;

	if (!prepare)
		return 0;

	for (i = 0; i < atoms->count; i++) {
		struct cas_atomic_io *this = &atoms[i];

		CAS_DEBUG_PARAM("Sub-atomic IO preparation(%u), Addr = %llu, "
				"bytes = %u, dir = %d", i, this->addr,
				this->bytes, dir);

		result |= prepare(io, this);
	}

	return result;
}

static void cas_atomic_fire_io(struct ocf_io *io,
	cas_prepare_atom_pfn_t prepare,
	bool write_zero)
{
	int dir = io->dir;

	/* Create atomic IOs context, mainly allocations */
	struct cas_atomic_io *atoms = cas_atomic_alloc(dir, io, write_zero);

	if (!atoms) {
		CAS_DEBUG_MSG("Memory allocation ERROR");
		goto _submit_io_ERROR;
	}

	/* Prepare IOs, mainly coping data */
	if (cas_atomic_prepare_atoms(io, prepare, atoms)) {
		CAS_DEBUG_MSG("Preparation ERROR");
		goto _submit_io_ERROR;
	}

	/* Send IO */
	atomic_inc(&atoms->req_remaining);
	cas_atomic_fire_atoms(dir, io, atoms);
	cas_atomic_end_atom(atoms, 0);

	return;

_submit_io_ERROR:
	if (atoms)
		cas_atomic_dealloc(atoms);

	io->end(io, -EIO);
}

static void cas_atomic_submit_flush_bio(struct cas_atomic_io *atom)
{
	struct request *req = atom->request;
	struct bd_object *bdobj = bd_object(atom->volume);
	unsigned int ns_id = bdobj->atomic_params.nsid;
	struct nvme_command *cmd = &atom->cmd;
	unsigned long *cmd_addr = blk_mq_rq_to_pdu(req);

	cmd->rw.opcode = nvme_cmd_flush;
	cmd->rw.nsid = cpu_to_le32(ns_id);

	*cmd_addr = (unsigned long)cmd;

	req->cmd_type = REQ_TYPE_DRV_PRIV;

	req->timeout = ADMIN_TIMEOUT;

	req->cmd = (unsigned char *) cmd;
	req->cmd_len = sizeof(*cmd);
	req->special = NULL;
	req->end_io_data = atom;

	/* Additional completion for request */
	atomic_inc(&atom->master->req_remaining);

	/* Send NVMe flush command */
	blk_execute_rq_nowait(req->q, NULL, req, 0, cas_atomic_end_request);
}

static int cas_atomic_submit_discard_bio(struct cas_atomic_io *atom)
{
	struct request *req = atom->request;
	struct nvme_command *cmd = &atom->cmd;
	struct bd_object *bdobj = bd_object(atom->volume);
	unsigned int ns_id = bdobj->atomic_params.nsid;
	struct nvme_dsm_range *nvm_discard;
	struct page *page;
	int offset;
	unsigned long *cmd_addr = blk_mq_rq_to_pdu(req);

	nvm_discard = kmalloc(sizeof(*nvm_discard), GFP_NOIO);
	if (!nvm_discard) {
		return -ENOMEM;
	}

	nvm_discard->cattr = cpu_to_le32(0);
	nvm_discard->nlb = cpu_to_le32(CAS_BIO_BISIZE(atom->bio) >> SECTOR_SHIFT);
	nvm_discard->slba = cpu_to_le64(CAS_BIO_BISECTOR(atom->bio));

	cmd->dsm.opcode = nvme_cmd_dsm;
	cmd->dsm.nsid = cpu_to_le32(ns_id);
	cmd->dsm.nr = 0;
	cmd->dsm.attributes = cpu_to_le32(NVME_DSMGMT_AD);

	req->completion_data = nvm_discard;
	page = virt_to_page(nvm_discard);
	offset = offset_in_page(nvm_discard);
	blk_add_request_payload(req, page, offset, sizeof(*nvm_discard));

	req->__sector = CAS_BIO_BISECTOR(atom->bio);
	req->__data_len = CAS_BIO_BISIZE(atom->bio);
	req->ioprio = bio_prio(atom->bio);

	req->timeout = ADMIN_TIMEOUT;
	req->end_io_data = atom;
	req->cmd_type = REQ_TYPE_DRV_PRIV;
	req->cmd_flags = CAS_BIO_DISCARD;

	req->errors = 0;

	*cmd_addr = (unsigned long)cmd;

	/* Additional completion for request */
	atomic_inc(&atom->master->req_remaining);

	/* Send NVMe flush command */
	blk_execute_rq_nowait(req->q, NULL, req, 0, cas_atomic_end_request);

	return 0;
}

static int cas_atomic_special_req_prepare(struct cas_atomic_io *atom,
	struct ocf_io *io)
{
	struct bd_object *bdobj = bd_object(ocf_io_get_volume(io));
	struct block_device *bdev = bdobj->btm_bd;

	CAS_DEBUG_TRACE();
	atom->master = atom;
	atom->count = 1;
	atom->cmpl_fn = io->end;
	atom->cmpl_context = io;
	atom->volume = ocf_io_get_volume(io);
	atom->flags = io->flags;
	atomic_set(&atom->req_remaining, 1);

	atom->bio = bio_alloc(GFP_NOIO, 1);
	if (!atom->bio) {
		CAS_PRINT_RL(KERN_ERR "Couldn't allocate memory for bio\n");
		return -ENOMEM;
	}

	atom->bio->bi_end_io = CAS_REFER_BLOCK_CALLBACK(cas_atomic_fire_atom);
	atom->bio->bi_bdev = bdev;
	atom->bio->bi_private = atom;

	return 0;
}

void cas_atomic_submit_discard(struct ocf_io *io)
{
	struct bd_object *bdobj = bd_object(ocf_io_get_volume(io));
	struct block_device *bdev = bdobj->btm_bd;
	struct request_queue *q = bdev_get_queue(bdev);
	int result = 0;

	struct cas_atomic_io *atom = NULL;
	struct blkio *blkio = cas_io_to_blkio(io);

	CAS_DEBUG_TRACE();

	if (!q) {
		/* No queue, error */
		io->end(io, -EINVAL);
		return;
	}

	/* Allocate and setup control structure. */
	atom = env_mpool_new(atomic_io_allocator, 1);
	if (!atom) {
		CAS_PRINT_RL(KERN_ERR "Couldn't allocate memory for IO ctrl\n");
		io->end(io, -ENOMEM);
		return;
	}

	result = cas_atomic_special_req_prepare(atom, io);
	if (result) {
		blkio->error = result;
		goto out;
	}

	/* Increase IO reference counter for FLUSH IO */
	ocf_io_get(io);

	/* Set up specific field */
	atom->discard = true;
	CAS_BIO_OP_FLAGS(atom->bio) = CAS_BIO_DISCARD;
	CAS_BIO_BISECTOR(atom->bio) = io->addr / SECTOR_SIZE;
	CAS_BIO_BISIZE(atom->bio) = io->bytes;

	atom->request = cas_blk_make_request(q, atom->bio, GFP_NOIO);
	if (IS_ERR(atom->request)) {
		blkio->error = PTR_ERR(atom->request);
		goto out;
	}

	atomic_inc(&atom->req_remaining);
	result = cas_atomic_submit_discard_bio(atom);
	if (result)
		blkio->error = result;

out:
	cas_atomic_end_atom(atom, blkio->error);
}

void cas_atomic_submit_flush(struct ocf_io *io)
{
	struct bd_object *bdobj = bd_object(ocf_io_get_volume(io));
	struct block_device *bdev = bdobj->btm_bd;
	struct request_queue *q = bdev_get_queue(bdev);
	int result = 0;
	struct cas_atomic_io *atom = NULL;
	struct blkio *blkio = cas_io_to_blkio(io);

	CAS_DEBUG_TRACE();

	if (!q) {
		io->end(io, -EINVAL);
		return;
	}

	if (!CAS_CHECK_QUEUE_FLUSH(q)) {
		/* This block device does not support flush */
		io->end(io, 0);
		return;
	}

	/* Allocate and setup control structure. */
	atom = env_mpool_new(atomic_io_allocator, 1);
	if (!atom) {
		CAS_PRINT_RL(KERN_ERR "Couldn't allocate memory for IO ctrl\n");
		io->end(io, -ENOMEM);
		return;
	}

	/* Increase IO reference counter for FLUSH IO */
	ocf_io_get(io);

	result = cas_atomic_special_req_prepare(atom, io);
	if (result) {
		CAS_PRINT_RL(CAS_KERN_ERR "Couldn't allocate memory for BIO\n");
		blkio->error = -ENOMEM;
		goto out;
	}

	/* Set up specific field */
	atom->dir = OCF_WRITE;

	atom->request = cas_blk_make_request(q, atom->bio, GFP_NOIO);
	if (IS_ERR(atom->request)) {
		blkio->error = PTR_ERR(atom->request);
		goto out;
	}

	atomic_inc(&atom->req_remaining);
	cas_atomic_submit_flush_bio(atom);

out:
	cas_atomic_end_atom(atom, blkio->error);
}

void cas_atomic_submit_io(struct ocf_io *io)
{
	CAS_DEBUG_TRACE();

	if (CAS_IS_SET_FLUSH(io->flags)) {
		/* FLUSH */
		cas_atomic_submit_flush(io);
		return;
	}

	if (unlikely(!io->bytes)) {
		CAS_PRINT_RL(KERN_ERR "Zero length request\n");
		io->end(io, -EINVAL);
		return;
	}

	cas_atomic_fire_io(io, io->dir == OCF_READ ? cas_atomic_rd_prepare :
			cas_atomic_wr_prepare, false);
}

void cas_atomic_submit_metadata(struct ocf_io *io)
{
	BUG_ON(io->dir != OCF_READ);

	CAS_DEBUG_TRACE();

	if (unlikely(!io->bytes)) {
		CAS_PRINT_RL(CAS_KERN_ERR "Zero length request\n");
		io->end(io, -EINVAL);
		return;
	}

	cas_atomic_fire_io(io, cas_atomic_rd_metadata_prepare, false);
}

unsigned int cas_atomic_get_max_io_size(ocf_volume_t volume)
{
	struct block_device *bd;

	if (!volume)
		return 0;

	bd = bd_object(volume)->btm_bd;
	if (!bd->bd_disk)
		return 0;

	return queue_max_sectors(bd->bd_disk->queue) << SECTOR_SHIFT;
}

void cas_atomic_close_object(ocf_volume_t volume)
{
	struct bd_object *bdobj = bd_object(volume);

	if(bdobj->btm_wq)
		destroy_workqueue(bdobj->btm_wq);

	block_dev_close_object(volume);
}

int cas_atomic_open_object(ocf_volume_t volume, void *volume_params)
{
	int result;
	struct bd_object *bdobj = NULL;

	if (!volume_params)
		return -EINVAL;

	result = block_dev_open_object(volume, volume_params);
	if (result)
		return result;

	bdobj = bd_object(volume);

	memcpy(&bdobj->atomic_params, volume_params,
			sizeof(bdobj->atomic_params));

	bdobj->btm_wq = create_workqueue("CAS_AT_ZER");
	if (!bdobj->btm_wq) {
		cas_atomic_close_object(volume);
		result = -ENOMEM;
		goto end;
	}

end:
	return result;
}

uint64_t cas_atomic_get_length(ocf_volume_t volume)
{
	struct bd_object *bdobj = bd_object(volume);

	return bdobj->atomic_params.size;
}

/* context to keep track of write_zero progress across child IOs */
struct cas_atomic_write_zero_ctx
{
	struct ocf_io *sub_io;
	struct ocf_io *original_io;
	struct work_struct cmpl_work;
	unsigned step_size;
};

static void _cas_atomic_write_zeroes_end(struct cas_atomic_write_zero_ctx *ctx,
		int error)
{
	struct ocf_io *io = ctx->original_io;

	/* end master io */
	io->end(io, error);
	ocf_io_put(io);

	/* cleanup context */
	ocf_io_put(ctx->sub_io);
	kfree(ctx);
}

/* atomic write zerores I/O completion */
static void _cas_atomic_write_zeroes_step_cmpl(struct ocf_io *io, int error)
{
	struct cas_atomic_write_zero_ctx *ctx = io->priv1;
	struct bd_object *bdobj = bd_object(ocf_io_get_volume(io));
	const unsigned bytes_processed = (io->addr - ctx->original_io->addr)
			+ io->bytes;
	const unsigned bytes_left = ctx->original_io->bytes - bytes_processed;

	BUG_ON(io->bytes > ctx->step_size);

	/* update I/O address and size */
	io->addr += io->bytes;
	io->bytes = min(bytes_left, ctx->step_size);

	if (!bytes_left || error) {
		_cas_atomic_write_zeroes_end(ctx, error);
	} else {
		/* submit next IO from work context */
		queue_work(bdobj->btm_wq, &ctx->cmpl_work);
	}
}

/* work routine to schedule next portion of write zero I/O */
void _cas_atomic_write_zeroes_work(struct work_struct *work)
{
	struct cas_atomic_write_zero_ctx *ctx = container_of(work,
			struct cas_atomic_write_zero_ctx, cmpl_work);

	cas_atomic_fire_io(ctx->sub_io, NULL, true);
}

void cas_atomic_submit_write_zeroes(struct ocf_io *io)
{
	/* send 8 atoms in each I/O */
	const unsigned step_size = min(cas_atomic_max_io_sectors()
			* SECTOR_SIZE * 8, io->bytes);
	struct cas_atomic_write_zero_ctx *ctx = NULL;
	int result = 0;

	if (unlikely(!io->bytes)) {
		CAS_PRINT_RL(CAS_KERN_ERR "Zero length request\n");
		result = -EINVAL;
		goto error;
	}

	ctx = kmalloc(sizeof(*ctx), GFP_NOIO);
	if (!ctx) {
		result = -ENOMEM;
		goto error;
	}

	ctx->sub_io = ocf_volume_new_io(ocf_io_get_volume(io), io->io_queue,
			io->addr, min(io->bytes, step_size),
			OCF_WRITE, 0, 0);
	if (!ctx->sub_io) {
		result = -ENOMEM;
		goto error_after_ctx;
	}

	/* set up context */
	ctx->step_size = step_size;
	ctx->original_io = io;
	INIT_WORK(&ctx->cmpl_work, _cas_atomic_write_zeroes_work);

	/* get reference to original io */
	ocf_io_get(io);

	/* set up sub-io */
	ocf_io_set_cmpl(ctx->sub_io, ctx, NULL, _cas_atomic_write_zeroes_step_cmpl);

	cas_atomic_fire_io(ctx->sub_io, NULL, true);

	return;

error_after_ctx:
	kfree(ctx);
error:
	io->end(io, result);
}

static void atomic_dev_deinit(void)
{
	if (atomic_io_allocator) {
		env_mpool_destroy(atomic_io_allocator);
		atomic_io_allocator = NULL;
	}
}

const struct ocf_volume_properties cas_object_atomic_properties = {
	.name = "Atomic_Writes_NVMe",
	.io_priv_size = sizeof(struct blkio),
	.volume_priv_size = sizeof(struct bd_object),
	.caps = {
		.atomic_writes = 1,
	},
	.ops = {
		.submit_io = cas_atomic_submit_io,
		.submit_flush = cas_atomic_submit_flush,
		.submit_discard = cas_atomic_submit_discard,
		.submit_metadata = cas_atomic_submit_metadata,
		.submit_write_zeroes = cas_atomic_submit_write_zeroes,
		.open = cas_atomic_open_object,
		.close = block_dev_close_object,
		.get_max_io_size = cas_atomic_get_max_io_size,
		.get_length = cas_atomic_get_length,
	},
	.io_ops = {
		.set_data = cas_blk_io_set_data,
		.get_data = cas_blk_io_get_data,
	},
	.deinit = atomic_dev_deinit
};

int atomic_dev_init(void)
{
	int ret;

	ret = ocf_ctx_register_volume_type(cas_ctx, ATOMIC_DEVICE_VOLUME,
			&cas_object_atomic_properties);

	if (ret < 0)
		return -EINVAL;

	atomic_io_allocator = env_mpool_create(0, sizeof(struct cas_atomic_io),
			GFP_NOIO, 1, true, NULL, "cas_atomic_io", true);

	if (!atomic_io_allocator) {
		ocf_ctx_unregister_volume_type(cas_ctx, ATOMIC_DEVICE_VOLUME);
		return -ENOMEM;
	}

	return 0;
}

#else

int atomic_dev_init(void)
{
	return 0;
}

#endif
