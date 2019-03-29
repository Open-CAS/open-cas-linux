/*
* Copyright(c) 2012-2019 Intel Corporation
* SPDX-License-Identifier: BSD-3-Clause-Clear
*/

#include "vol_blk_utils.h"

static void cas_io_iter_advanced(struct bio_vec_iter *iter, uint32_t bytes)
{
	BUG_ON(bytes > iter->len);

	iter->len -= bytes;
	iter->offset += bytes;

	if (iter->len) {
		/* Still in this item, bytes to be processed */
		return;
	}

	/* Move to next item in data vector */
	iter->idx++;
	if (iter->idx < iter->vec_size) {
		iter->ivec = &iter->vec[iter->idx];
		iter->len = iter->ivec->bv_len;
		iter->offset = iter->ivec->bv_offset;
	} else {
		iter->ivec = NULL;
		iter->len = 0;
		iter->offset = 0;
	}
}

uint32_t cas_io_iter_cpy(struct bio_vec_iter *dst, struct bio_vec_iter *src,
		uint32_t bytes)
{
	uint32_t to_copy, written = 0;
	void *adst, *asrc;

	if (dst->idx >= dst->vec_size)
		return 0;

	BUG_ON(dst->offset + dst->len > PAGE_SIZE);

	if (src->idx >= src->vec_size)
		return 0;

	BUG_ON(src->offset + src->len > PAGE_SIZE);

	while (bytes) {
		to_copy = min(dst->len, src->len);
		to_copy = min(to_copy, bytes);
		if (to_copy == 0) {
			/* No more bytes for coping */
			break;
		}

		adst = page_address(dst->ivec->bv_page) + dst->offset;
		asrc = page_address(src->ivec->bv_page) + src->offset;

		memcpy(adst, asrc, to_copy);

		bytes -= to_copy;
		written += to_copy;

		cas_io_iter_advanced(dst, to_copy);
		cas_io_iter_advanced(src, to_copy);
	}

	return written;
}

uint32_t cas_io_iter_cpy_from_data(struct bio_vec_iter *dst,
		const void *src, uint32_t bytes)
{
	uint32_t to_copy, written = 0;
	void *adst;
	const void *asrc;

	if (dst->idx >= dst->vec_size)
		return 0;

	BUG_ON(dst->offset + dst->len > PAGE_SIZE);

	while (bytes) {
		to_copy = min(dst->len, bytes);
		if (to_copy == 0) {
			/* No more bytes for coping */
			break;
		}

		adst = page_address(dst->ivec->bv_page) + dst->offset;
		asrc = src + written;

		memcpy(adst, asrc, to_copy);

		bytes -= to_copy;
		written += to_copy;

		cas_io_iter_advanced(dst, to_copy);
	}

	return written;
}

uint32_t cas_io_iter_cpy_to_data(void *dst, struct bio_vec_iter *src,
		uint32_t bytes)
{
	uint32_t to_copy, written = 0;
	void *adst, *asrc;

	BUG_ON(dst == NULL);

	if (src->idx >= src->vec_size)
		return 0;

	BUG_ON(src->offset + src->len > PAGE_SIZE);

	while (bytes) {
		to_copy = min(bytes, src->len);
		if (to_copy == 0) {
			/* No more bytes for coping */
			break;
		}

		adst = dst + written;
		asrc = page_address(src->ivec->bv_page) + src->offset;

		memcpy(adst, asrc, to_copy);

		bytes -= to_copy;
		written += to_copy;

		cas_io_iter_advanced(src, to_copy);
	}

	return written;
}

uint32_t cas_io_iter_move(struct bio_vec_iter *iter, uint32_t bytes)
{
	uint32_t to_move, moved = 0;

	if (iter->idx >= iter->vec_size)
		return 0;

	BUG_ON(iter->offset + iter->len > PAGE_SIZE);

	while (bytes) {
		to_move = min(iter->len, bytes);
		if (to_move == 0) {
			/* No more bytes for coping */
			break;
		}

		bytes -= to_move;
		moved += to_move;

		cas_io_iter_advanced(iter, to_move);
	}

	return moved;
}

uint32_t cas_io_iter_zero(struct bio_vec_iter *dst, uint32_t bytes)
{
	uint32_t to_fill, zeroed = 0;
	void *adst;

	if (dst->idx >= dst->vec_size)
		return 0;

	BUG_ON(dst->offset + dst->len > PAGE_SIZE);

	while (bytes) {
		to_fill = min(dst->len, (typeof(dst->len))PAGE_SIZE);
		if (to_fill == 0) {
			/* No more bytes for coping */
			break;
		}

		adst = page_address(dst->ivec->bv_page) + dst->offset;

		memset(adst, 0, to_fill);

		bytes -= to_fill;
		zeroed += to_fill;

		cas_io_iter_advanced(dst, to_fill);
	}

	return zeroed;
}

/*
 *
 */
int cas_blk_io_set_data(struct ocf_io *io,
		ctx_data_t *ctx_data, uint32_t offset)
{
	struct blkio *blkio = cas_io_to_blkio(io);
	struct blk_data *data = ctx_data;

	/* Set BIO vector (IO data) and initialize iterator */
	blkio->data = data;
	if (blkio->data) {
		cas_io_iter_init(&blkio->iter, blkio->data->vec,
				blkio->data->size);

		/* Move into specified offset in BIO vector iterator */
		if (offset != cas_io_iter_move(&blkio->iter, offset)) {
			/* TODO Log message */
			blkio->error = -ENOBUFS;
			return -ENOBUFS;
		}
	}

	return 0;
}

/*
 *
 */
ctx_data_t *cas_blk_io_get_data(struct ocf_io *io)
{
	struct blkio *blkio = cas_io_to_blkio(io);

	return blkio->data;
}

#if defined(CAS_NVME_PARTIAL)

#include "utils/utils_nvme.h"

int cas_blk_identify_type_by_bdev(struct block_device *bdev,
		uint8_t *type, struct atomic_dev_params *atomic_params)
{
	struct nvme_id_ns *ns;
	unsigned int nsid, selected, ms, ds, pi, elba, sbsupp;
	long long int ret = 0;
	struct atomic_dev_params atomic_params_int = {0};

	ns = kmalloc(sizeof(*ns), GFP_KERNEL);
	if (!ns)
		return -OCF_ERR_NO_MEM;

	ret = cas_nvme_get_nsid(bdev, &nsid);
	if (ret < 0) {
		/*
		 * We cannot obtain NSID which means we are not dealing with
		 * NVMe device
		 */
		goto out1;
	}

	ret = cas_nvme_identify_ns(bdev, nsid, ns);
	if (ret < 0) {
		/*
		 * We cannot obtain ns structure which means we ARE dealing with
		 * NVMe device but can not recognize format so let's treat that
		 * device as block device
		 */
		goto out1;
	}

	selected = ns->flbas & 0xf;
	ms = ns->lbaf[selected].ms;
	ds = ns->lbaf[selected].ds;
	pi = ns->dps & 0x7;
	elba = !!(ns->flbas & (1<<4));
	sbsupp = !!(ns->mc & (1<<1));

	atomic_params_int.is_atomic_capable = 1;
	atomic_params_int.nsid = nsid;
	atomic_params_int.size = (ns->nsze << (ds - 9)) * SECTOR_SIZE;

	if (pi != 0) {
		/* We don't support formats which have
		 * enable Protection Information feature.
		 */
		ret = -KCAS_ERR_NVME_BAD_FORMAT;
		goto out2;
	}

	switch (ms) {
	case 0:
		/* NVMe metadata features disabled, so we handle it as
		 * regular block device
		 */

		if (ds != 9 && ds != 12) {
			ret = -KCAS_ERR_NVME_BAD_FORMAT;
			goto out2;
		}

		*type = BLOCK_DEVICE_VOLUME;
		atomic_params_int.metadata_mode = ATOMIC_METADATA_MODE_NONE;

#if !defined(CAS_NVME_FULL)
		/*
		 * Only partial support user can't using
		 * device in atomic mode, so mode is optimal
		 */
		atomic_params_int.is_mode_optimal = 1;
		break;
#else
		if (bdev == bdev->bd_contains) {
			/*
			 * Entire device - format isn't optimal
			 */
			atomic_params_int.is_mode_optimal = 0;
		} else {
			/*
			 * Partition - format is optimal, user can't using
			 * partitions in atomic mode
			 */
			atomic_params_int.is_mode_optimal = 1;
		}
		break;

	case 8:
		/* For atomic writes we support only metadata size 8B and
		 * data size 512B
		 */

		if (ds != 9) {
			ret = -KCAS_ERR_NVME_BAD_FORMAT;
			goto out2;
		}

		*type = ATOMIC_DEVICE_VOLUME;
		atomic_params_int.metadata_mode = elba ?
				ATOMIC_METADATA_MODE_ELBA :
				ATOMIC_METADATA_MODE_SEPBUF;
		atomic_params_int.is_mode_optimal = sbsupp ? !elba : 1;
		break;
#endif

	default:
		ret = -KCAS_ERR_NVME_BAD_FORMAT;
	}

	if (atomic_params)
		*atomic_params = atomic_params_int;

	goto out2;
out1:
	*type = BLOCK_DEVICE_VOLUME;
	ret = 0;
out2:
	kfree(ns);
	return ret;
}

static inline int _cas_detect_blk_type(const char *path, uint8_t *type,
		struct atomic_dev_params *atomic_params)
{
	int ret;
	struct block_device *bdev;
	char holder[] = "CAS DETECT\n";

	bdev = OPEN_BDEV_EXCLUSIVE(path, FMODE_READ, holder);
	if (IS_ERR(bdev))
		return -OCF_ERR_NOT_OPEN_EXC;

	ret = cas_blk_identify_type_by_bdev(bdev, type, atomic_params);
	CLOSE_BDEV_EXCLUSIVE(bdev, FMODE_READ);
	return ret;
}

#else

static inline int _cas_detect_blk_type(const char *path, uint8_t *type,
		struct atomic_dev_params *atomic_params)
{
	/*
	 * NVMe is not supported with given kernel version, so we
	 * have no way to figure out what the current NVMe format
	 * is. In this situation we make a naive assumption that
	 * it's formatted to LBA size 512B, and try to treat it
	 * as regular block device.
	 */
	*type = BLOCK_DEVICE_VOLUME;
	return 0;
}

int cas_blk_identify_type_by_bdev(struct block_device *bdev,
		uint8_t *type, struct atomic_dev_params *atomic_params)
{
	*type = BLOCK_DEVICE_VOLUME;
	return 0;
}
#endif

int cas_blk_open_volume_by_bdev(ocf_volume_t *vol,
		struct block_device *bdev)
{
	struct atomic_dev_params atomic_params = {0};
	struct bd_object *bdobj;
	uint8_t type;
	int ret;

	ret = cas_blk_identify_type_by_bdev(bdev, &type, &atomic_params);
	if (ret)
		goto err;

	ret = ocf_ctx_volume_create(cas_ctx, vol, NULL, type);
	if (ret)
		goto err;

	bdobj = bd_object(*vol);

	bdobj->btm_bd = bdev;
	bdobj->opened_by_bdev = true;

	ocf_volume_open(*vol);

	return 0;

err:
	return ret;
}

void cas_blk_close_volume(ocf_volume_t vol)
{
	ocf_volume_close(vol);
	ocf_volume_deinit(vol);
	env_free(vol);
}

int _cas_blk_identify_type(const char *path, uint8_t *type,
		struct atomic_dev_params *atomic_params)
{
	struct file *file;
	int result = 0;

	file = filp_open(path, O_RDONLY, 0);
	if (IS_ERR(file))
		return -OCF_ERR_INVAL_VOLUME_TYPE;

	if (S_ISBLK(FILE_INODE(file)->i_mode))
		*type = BLOCK_DEVICE_VOLUME;
	else if (S_ISCHR(FILE_INODE(file)->i_mode))
		*type = NVME_CONTROLLER;
	else
		result = -OCF_ERR_INVAL_VOLUME_TYPE;

	filp_close(file, 0);
	if (result)
		return result;

	if (*type == BLOCK_DEVICE_VOLUME) {
		result = _cas_detect_blk_type(path, type, atomic_params);
		if (result < 0)
			return result;
	}

	return 0;
}

int cas_blk_identify_type(const char *path, uint8_t *type)
{
	return _cas_blk_identify_type(path, type, NULL);
}

int cas_blk_identify_type_atomic(const char *path, uint8_t *type,
		struct atomic_dev_params *atomic_params)
{
	return _cas_blk_identify_type(path, type, atomic_params);
}

