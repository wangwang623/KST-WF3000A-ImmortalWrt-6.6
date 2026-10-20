# KST-WF3000A —— 128MB Flash / NMBM 114MiB 布局（单一布局，不再编 256M 变体）
#
# 用法：本文件内容由 scripts/prepare-source.py 追加到
#       openwrt/target/linux/mediatek/image/filogic.mk 末尾
#
# ── 与恩山「小圆」实测可用版本的对照 ──────────────────────────
# 小圆同时编了 kst_wf3000a(114M) 与 kst_wf3000a-256m(256M) 两种，
# 本机 flash 为 128MB，只需要 114M 一种，256M 变体已删除。
#
# 【★ 关键澄清】小圆原本写的这两行是【死引用】：
#     DEVICE_PACKAGES := kmod-mt7981-firmware mt7981-wo-firmware
#   已递归核对 padavanonly/immortalwrt-mt798x-6.6 全部 12803 个文件：
#     · package/kernel/mt76 目录【不存在】
#     · 全树没有任何一个 Makefile 定义 mt7981-firmware / mt7981-wo-firmware
#       （"wo-firmware" 唯一命中只是一个 WED 补丁文件名）
#   ⇒ 这两个名字会被 make defconfig 静默丢弃，对无线【零作用】。
#
#   小圆的固件无线能用，真正的原因是他的 config 基于
#   defconfig/mt7981-ax3000.config —— 那份配置里有
#     CONFIG_PACKAGE_kmod-mt_wifi=y   （闭源驱动）
#   与这里的 DEVICE_PACKAGES 无关。
#
# 【本工程写法】保留 DEVICE_PACKAGES 指向真实存在的闭源包，双保险：
#   kmod-mt_wifi      package/mtk/drivers/mt_wifi     —— mt_wifi.ko
#   kmod-warp         package/mtk/drivers/warp        —— WED 硬件卸载
#   kmod-conninfra    package/mtk/drivers/conninfra   —— 连接基础设施
#   wifi-dats         package/mtk/drivers/wifi-profile—— mt7981 profile(.dat)
#   mtwifi-cfg        package/mtk/applications/mtwifi-cfg —— 无线配置工具
# config/wf3000a.config 里也各写了一份 =y。
#
# 115712k = 0x7100000，比 DTS 里 ubi 分区 0x7200000(116736k) 少 1MiB，
# 预留给 NMBM 坏块表 / UBI 开销。与小圆 114m 实测可启动的配置一致。

define Device/kst_wf3000a
  DEVICE_VENDOR := KST
  DEVICE_MODEL := WF3000A
  DEVICE_VARIANT := NMBM 114MiB layout
  DEVICE_DTS := mt7981b-kst-wf3000a
  DEVICE_DTS_DIR := ../dts
  SUPPORTED_DEVICES := kst,wf3000a
  DEVICE_PACKAGES := kmod-mt_wifi kmod-warp kmod-conninfra wifi-dats mtwifi-cfg
  UBINIZE_OPTS := -E 5
  BLOCKSIZE := 128k
  PAGESIZE := 2048
  IMAGE_SIZE := 115712k
  KERNEL_IN_UBI := 1
  IMAGES += factory.bin
  IMAGE/factory.bin := append-ubi | check-size $$$$(IMAGE_SIZE)
  IMAGE/sysupgrade.bin := sysupgrade-tar | append-metadata
  # ── 以下两行照抄小圆的实测定义 ──────────────────────────────
  # 语法与 filogic.mk 内其它机型完全一致（:= 与 = 在该文件里都有使用，
  # 这里是 = + $$(KDIR)，与源码第 554/577/757 行同一写法）。
  # 显式写出可确保生成 initramfs-kernel.bin
  # —— 那是"内存启动、不写 flash"的安全验证方式，强烈建议先刷它。
  KERNEL = kernel-bin | lzma | \
	fit lzma $$(KDIR)/image-$$(firstword $$(DEVICE_DTS)).dtb
  KERNEL_INITRAMFS = kernel-bin | lzma | \
	fit lzma $$(KDIR)/image-$$(firstword $$(DEVICE_DTS)).dtb with-initrd
endef
TARGET_DEVICES += kst_wf3000a
