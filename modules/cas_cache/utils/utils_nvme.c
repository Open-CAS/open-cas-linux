/*
* Copyright(c) 2012-2019 Intel Corporation
* SPDX-License-Identifier: BSD-3-Clause-Clear
*/

#if defined(CAS_NVME_PARTIAL)

#include "cas_cache.h"
#include "utils_nvme.h"
#include "utils_blk.h"

#include <linux/ioctl.h>
#include <linux/file.h>


int cas_nvme_get_nsid(struct block_device *bdev, unsigned int *nsid)
{
	int ret = 0;

	/*
	 * Maximum NSID is 0xFFFFFFFF, so theoretically there is no free
	 * room for error code. However it's unlikely that there will ever
	 * be device with such number of namespaces, so we treat this value
	 * as it was signed. Then in case of negative value we interpret it
	 * as an error code. Moreover in case of error we can be sure, that
	 * we deal with non-NVMe device, because this ioctl should never
	 * fail with NVMe driver.
	 */
	ret = ioctl_by_bdev(bdev, NVME_IOCTL_ID, (unsigned long)NULL);
	if (ret < 0)
		return ret;

	*nsid = (unsigned int)ret;
	return 0;
}

#define NVME_ID_CNS_NS 0x00
#define NVME_ID_CNS_CTRL 0x01

int cas_nvme_identify_ns(struct block_device *bdev, unsigned int nsid,
		struct nvme_id_ns *ns)
{
	struct nvme_admin_cmd cmd = { };
	unsigned long __user buffer;
	int ret = 0;

	buffer = cas_vm_mmap(NULL, 0, sizeof(*ns));
	if (IS_ERR((void *)buffer))
		return PTR_ERR((void *)buffer);

	cmd.opcode = nvme_admin_identify;
	cmd.nsid = cpu_to_le32(nsid);
	cmd.addr = (__u64)buffer;
	cmd.data_len = sizeof(*ns);
	cmd.cdw10 = NVME_ID_CNS_NS;
	ret = ioctl_by_bdev(bdev, NVME_IOCTL_ADMIN_CMD, (unsigned long)&cmd);
	if (ret < 0)
		goto out;

	ret = copy_from_user(ns, (void *)buffer, sizeof(*ns));
	if (ret > 0)
		ret = -EINVAL;
out:
	cas_vm_munmap(buffer, sizeof(*ns));
	return ret;
}

int cas_nvme_identify_ns_contorller(struct file *file, struct nvme_id_ns *ns)
{
	struct nvme_admin_cmd cmd = { };
	unsigned long __user buffer;
	mm_segment_t old_fs;
	int ret = 0;

	buffer = cas_vm_mmap(NULL, 0, sizeof(*ns));
	if (IS_ERR((void *)buffer))
		return PTR_ERR((void *)buffer);

	cmd.opcode = nvme_admin_identify;
	cmd.nsid = 1;
	cmd.addr = (__u64)buffer;
	cmd.data_len = sizeof(*ns);
	cmd.cdw10 = NVME_ID_CNS_NS;

	old_fs = get_fs();
	set_fs(KERNEL_DS);
	ret = file->f_op->unlocked_ioctl(file,
			NVME_IOCTL_ADMIN_CMD, (unsigned long)&cmd);
	set_fs(old_fs);
	if (ret < 0)
		goto out;

	ret = copy_from_user(ns, (void *)buffer, sizeof(*ns));
	if (ret > 0)
		ret = -EINVAL;
out:
	cas_vm_munmap(buffer, sizeof(*ns));
	return ret;
}

#if defined(CAS_NVME_FULL)

#define FORMAT_WORKAROUND_NOT_NEED 0
#define FORMAT_WORKAROUND_NEED 1

static int __cas_nvme_check_fw(struct nvme_id_ctrl *id_ctrl)
{
	/*
	 * If firmware is older then 8DV101H0 we need do
	 * workaround - make format twice. We need to compare
	 * only 5 last characters.
	 */

	return (strncmp(&id_ctrl->fr[3], "101H0", 5) < 0) ?
		FORMAT_WORKAROUND_NEED :
		FORMAT_WORKAROUND_NOT_NEED;
}

int cas_nvme_identify_ctrl(struct block_device *bdev,
		struct nvme_id_ctrl *id_ctrl)
{
	struct nvme_admin_cmd cmd = { };
	unsigned long __user buffer;
	int ret = 0;

	buffer = cas_vm_mmap(NULL, 0, sizeof(*id_ctrl));
	if (IS_ERR((void *)buffer))
		return PTR_ERR((void *)buffer);

	cmd.opcode = nvme_admin_identify;
	cmd.addr = (__u64)buffer;
	cmd.data_len = sizeof(*id_ctrl);
	cmd.cdw10 = NVME_ID_CNS_CTRL;

	ret = ioctl_by_bdev(bdev, NVME_IOCTL_ADMIN_CMD, (unsigned long)&cmd);
	if (ret < 0)
		goto out;

	ret = copy_from_user(id_ctrl, (void *)buffer, sizeof(*id_ctrl));
	if (ret > 0)
		ret = -EINVAL;

out:
	cas_vm_munmap(buffer, sizeof(*id_ctrl));
	return ret;
}

static int _cas_nvme_format_bdev(struct block_device *bdev, unsigned int nsid,
		int lbaf, int ms)
{
	struct nvme_admin_cmd cmd = { };

	cmd.opcode = nvme_admin_format_nvm;
	cmd.nsid = nsid;
	cmd.cdw10 = lbaf | ms<<4;
	cmd.timeout_ms = 1200000;
	return ioctl_by_bdev(bdev, NVME_IOCTL_ADMIN_CMD, (unsigned long)&cmd);
}

static int _cas_nvme_controller_identify(struct file *character_device_file,
		unsigned long __user buffer)
{
	struct nvme_admin_cmd cmd = { };
	mm_segment_t old_fs;
	int ret;

	old_fs = get_fs();

	cmd.opcode = nvme_admin_identify;
	cmd.nsid = 0;
	cmd.addr = (__u64)buffer;
	/* 1 - identify contorller, 0 - identify namespace */
	cmd.cdw10 = 1;
	cmd.data_len = 0x1000;

	set_fs(KERNEL_DS);
	ret = character_device_file->f_op->unlocked_ioctl(character_device_file,
			NVME_IOCTL_ADMIN_CMD, (unsigned long)&cmd);
	set_fs(old_fs);
	return ret;
}

static int _cas_nvme_format_controller(struct file *character_device_file,
		int lbaf, bool sbnsupp)
{
	struct nvme_admin_cmd cmd = { };
	mm_segment_t old_fs;
	int ret;

	old_fs = get_fs();

	/* Send format command to device */
	cmd.opcode = nvme_admin_format_nvm;
	cmd.nsid = 0xFFFFFFFF;
	cmd.cdw10 = lbaf | sbnsupp << 4;
	cmd.timeout_ms = 120000;
	cmd.addr = 0;

	set_fs(KERNEL_DS);
	ret = character_device_file->f_op->unlocked_ioctl(character_device_file,
			NVME_IOCTL_ADMIN_CMD, (unsigned long)&cmd);
	set_fs(old_fs);
	return ret;
}

static inline int find_lbaf(struct nvme_lbaf *lbaf, int cnt, int atomic)
{
	int ms = atomic ? 8 : 0;
	int i;

	for (i = 0; i <= cnt; ++i)
		if (lbaf[i].ms == ms && lbaf[i].ds == 9)
			return i;

	return -EINVAL;
}

/* context for async probe */
struct _probe_context
{
	struct completion cmpl;
	struct ocf_metadata_probe_status status;
	int error;
};

static void _cas_nvme_probe_cmpl(void *priv, int error,
		struct ocf_metadata_probe_status *status)
{
	struct _probe_context *ctx = (struct _probe_context*)priv;

	ctx->error = error;
	if (!error) {
		ctx->status = *status;
	}

	complete(&ctx->cmpl);
}

static int _cas_nvme_preformat_check(struct block_device *bdev, int force)
{
	ocf_volume_t volume;
	struct _probe_context probe_ctx;
	int ret = 0;

	if (bdev != bdev->bd_contains)
		return -KCAS_ERR_A_PART;

	if (cas_blk_get_part_count(bdev) > 1 && !force)
		return -KCAS_ERR_CONTAINS_PART;

	ret = cas_blk_open_volume_by_bdev(&volume, bdev);
	if (ret == -KCAS_ERR_NVME_BAD_FORMAT) {
		/* Current format is not supported by CAS, so we can be sure
		* that there is no dirty data. Do format
		*/
		return 0;
	} else if (ret) {
		/* An error occurred, stop processing */
		return ret;
	}

	init_completion(&probe_ctx.cmpl);
	ocf_metadata_probe(cas_ctx, volume, _cas_nvme_probe_cmpl, &probe_ctx);
	if (wait_for_completion_interruptible(&probe_ctx.cmpl)) {
		ocf_volume_close(volume);
		return -OCF_ERR_FLUSHING_INTERRUPTED;
	}

	if (probe_ctx.error == -ENODATA) {
		/* Cache was not detected on this device
		* NVMe can be formated
		*/
		ret = 0;
	} else if (probe_ctx.error == -EBUSY) {
		ret = -OCF_ERR_NOT_OPEN_EXC;
	} else if (probe_ctx.error) {
		/* Some error occurred, we do not have sure about clean cache */
		ret = -KCAS_ERR_FORMAT_FAILED;
	} else {
		/* Check if cache was closed in proper way */
		if (!probe_ctx.status.clean_shutdown ||
				probe_ctx.status.cache_dirty) {
			/* Dirty shutdown */
			ret = -KCAS_ERR_DIRTY_EXISTS_NVME;
		}

		if (force) {
			/* Force overwrites dirty shutdown */
			ret = 0;
		}
	}

	ocf_volume_close(volume);
	return ret;
}

static int _cas_nvme_format_namespace_by_path(const char *device_path,
		int metadata_mode, int force)
{
	struct nvme_id_ns *ns;
	struct nvme_id_ctrl *id;

	unsigned int nsid, sbnsupp = 0;
	int best_lbaf = 0;
	int ret = 0;
	struct block_device *bdev;
	char holder[] = "CAS FORMAT\n";

	ns = kmalloc(sizeof(*ns), GFP_KERNEL);
	if (!ns)
		return -OCF_ERR_NO_MEM;

	id = kmalloc(sizeof(*id), GFP_KERNEL);
	if (!id) {
		ret = -OCF_ERR_NO_MEM;
		goto out1;
	}

	bdev = OPEN_BDEV_EXCLUSIVE(device_path,
			FMODE_READ | FMODE_WRITE | FMODE_EXCL, holder);
	if (IS_ERR(bdev)) {
		if (PTR_ERR(bdev) == -EBUSY)
			ret = -OCF_ERR_NOT_OPEN_EXC;
		else
			ret = -OCF_ERR_INVAL_VOLUME_TYPE;

		goto out1;
	}

	ret = cas_nvme_get_nsid(bdev, &nsid);
	if (ret < 0) {
		ret = -KCAS_ERR_NOT_NVME;
		goto out2;
	}

	ret = _cas_nvme_preformat_check(bdev, force);
	if (ret)
		goto out2;

	ret = cas_nvme_identify_ns(bdev, nsid, ns);
	if (ret < 0) {
		ret = -KCAS_ERR_FORMAT_FAILED;
		goto out2;
	}

	if (metadata_mode == CAS_METADATA_MODE_NORMAL) {
		best_lbaf = find_lbaf(ns->lbaf, ns->nlbaf, 0);
		sbnsupp = 0;
	} else if (metadata_mode == CAS_METADATA_MODE_ATOMIC) {
		best_lbaf = find_lbaf(ns->lbaf, ns->nlbaf, 1);
		sbnsupp = !(ns->mc & (1<<1));
	}

	if (best_lbaf < 0) {
		ret = -KCAS_ERR_FORMAT_FAILED;
		goto out2;
	}

	ret = cas_nvme_identify_ctrl(bdev, id);
	if (ret < 0) {
		ret = -KCAS_ERR_FORMAT_FAILED;
		goto out2;
	}

	if (__cas_nvme_check_fw(id) == FORMAT_WORKAROUND_NEED) {
		/*
		 * If firmware is older then 8DV101H0 we need do
		 * workaround - make format twice.
		 */
		ret = _cas_nvme_format_bdev(bdev, nsid, best_lbaf, sbnsupp);
		if (ret)
			goto out2;
	}

	ret = _cas_nvme_format_bdev(bdev, nsid, best_lbaf, sbnsupp);
	if (ret)
		goto out2;

	ret = ioctl_by_bdev(bdev, BLKRRPART, (unsigned long)NULL);
out2:
	CLOSE_BDEV_EXCLUSIVE(bdev, FMODE_READ | FMODE_WRITE | FMODE_EXCL);
out1:
	kfree(id);
	kfree(ns);
	return ret;
}

static int _cas_nvme_get_bdev_from_controller(struct block_device **bdev,
		int major, int minor, int namespace_number)
{
	mm_segment_t old_fs;
	char *sys_path;
	struct file *file;
	char readbuffer[12] = {0};
	char holder[] = "CAS FORMAT\n";
	int ret = 0;

	sys_path = kzalloc(sizeof(char)*MAX_STR_LEN, GFP_KERNEL);
	if (!sys_path)
		return -OCF_ERR_NO_MEM;

	sprintf(sys_path, "/sys/dev/char/%d:%d/nvme%dn%d/dev",
			major, minor, minor, namespace_number);

	file = filp_open(sys_path, O_RDONLY, 0);
	kfree(sys_path);
	if (IS_ERR(file))
		return -KCAS_ERR_FORMAT_FAILED;

	old_fs = get_fs();
	set_fs(KERNEL_DS);
	ret = file->f_op->read(file, readbuffer, sizeof(readbuffer),
			&file->f_pos);
	set_fs(old_fs);
	filp_close(file, 0);
	if (ret < 0)
		return -KCAS_ERR_FORMAT_FAILED;

	ret = sscanf(readbuffer, "%d:%d", &major, &minor);
	if (ret < 0)
		return -KCAS_ERR_FORMAT_FAILED;

	*bdev = blkdev_get_by_dev(MKDEV(major, minor),
			FMODE_READ | FMODE_WRITE | FMODE_EXCL, holder);
	if (IS_ERR(*bdev))
		return -OCF_ERR_INVAL_VOLUME_TYPE;

	return 0;
}

static int _cas_nvme_format_character_device(const char *device_path,
		int metadata_mode, int force)
{
	mm_segment_t old_fs;
	int ret;
	struct file *character_device_file = NULL;
	struct nvme_id_ctrl *ctrl;
	unsigned long __user buffer;
	struct kstat *stat;
	struct block_device **ndev = NULL;
	int i;
	struct nvme_id_ns *ns;
	int best_lbaf = 0;
	int sbnsupp = 0;

	ctrl = kzalloc(sizeof(struct nvme_id_ctrl), GFP_KERNEL);
	buffer = cas_vm_mmap(NULL, 0, sizeof(*ctrl));
	stat = kmalloc(sizeof(struct kstat), GFP_KERNEL);
	ns = kmalloc(sizeof(*ns), GFP_KERNEL);

	old_fs = get_fs();

	if (!ctrl || !buffer || !stat || !ns) {
		ret = -OCF_ERR_NO_MEM;
		goto out1;
	}

	character_device_file = filp_open(device_path, O_RDWR | O_EXCL, 0);
	if (IS_ERR(character_device_file)) {
		ret = -OCF_ERR_INVAL_VOLUME_TYPE;
		goto out1;
	}

	ret = _cas_nvme_controller_identify(character_device_file, buffer);
	if (ret < 0) {
		ret = KCAS_ERR_FORMAT_FAILED;
		goto out1;
	}

	ret = copy_from_user(ctrl, (void *)buffer, sizeof(*ctrl));
	if (ret)
		goto out1;

	ndev = kmalloc_array(ctrl->nn, sizeof(struct block_device), GFP_KERNEL);
	if (!ndev) {
		ret = -OCF_ERR_NO_MEM;
		goto out1;
	}

	set_fs(KERNEL_DS);
	ret = vfs_stat(device_path, stat);
	set_fs(old_fs);
	if (ret)
		goto out1;

	for (i = 1; i <= ctrl->nn; i++) {
		ret = _cas_nvme_get_bdev_from_controller(&ndev[i-1],
				MAJOR(stat->rdev), MINOR(stat->rdev), i);
		if (ret) {
			i--;
			goto cleanup;
		}

		ret = _cas_nvme_preformat_check(ndev[i-1], force);
		if (ret)
			goto cleanup;
	}

	ret = cas_nvme_identify_ns_contorller(character_device_file, ns);
	if (ret)
		goto cleanup;

	if (metadata_mode == CAS_METADATA_MODE_NORMAL) {
		best_lbaf = find_lbaf(ns->lbaf, ns->nlbaf, 0);
		sbnsupp = 0;
	} else if (metadata_mode == CAS_METADATA_MODE_ATOMIC) {
		best_lbaf = find_lbaf(ns->lbaf, ns->nlbaf, 1);
		sbnsupp = !(ns->mc & (1<<1));
	}

	if (best_lbaf < 0) {
		ret = -KCAS_ERR_FORMAT_FAILED;
		goto cleanup;
	}

	if (__cas_nvme_check_fw(ctrl) == FORMAT_WORKAROUND_NEED) {
		/*
		 * If firmware is older then 8DV101H0 we need do
		 * workaround - make format twice.
		 */
		ret = _cas_nvme_format_controller(character_device_file,
			best_lbaf, sbnsupp);
		if (ret < 0) {
			ret = -KCAS_ERR_FORMAT_FAILED;
			goto cleanup;
		}
	}

	ret = _cas_nvme_format_controller(character_device_file,
			best_lbaf, sbnsupp);
	if (ret < 0)
		ret = -KCAS_ERR_FORMAT_FAILED;

cleanup:
	for (i = i-1; i >= 1; i--) {
		ret |= ioctl_by_bdev(ndev[i-1], BLKRRPART, (unsigned long)NULL);
		blkdev_put(ndev[i-1], FMODE_READ | FMODE_WRITE | FMODE_EXCL);
	}

out1:
	kfree(ndev);
	kfree(ctrl);
	kfree(stat);

	kfree(ns);
	cas_vm_munmap(buffer, sizeof(buffer));
	filp_close(character_device_file, 0);

	return ret;
}

int cas_nvme_format_optimal(const char *device_path, int metadata_mode,
		int force)
{
	int ret;
	uint8_t type;

	ret = cas_blk_identify_type(device_path, &type);
	if (ret == -OCF_ERR_INVAL_VOLUME_TYPE) {
		/* An error occurred, stop processing */
		return ret;
	}

	if (type == BLOCK_DEVICE_VOLUME || type == ATOMIC_DEVICE_VOLUME) {
		ret = _cas_nvme_format_namespace_by_path(device_path,
				metadata_mode, force);
	} else if (type == NVME_CONTROLLER && false) {
		/*
		 * TODO(rbaldyga): Make it safe with NVMe drives that do not
		 *       handle format change properly.
		 */
		ret = _cas_nvme_format_character_device(device_path,
				metadata_mode, force);
	} else {
		ret = -OCF_ERR_INVAL_VOLUME_TYPE;
	}

	return ret;
}

#endif

#endif
