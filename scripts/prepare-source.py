#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
WF3000A 板级移植安装脚本（构建时打补丁）

═══════════════════════════════════════════════════════════════
设计前提
────────
immortalwrt-mt798x-6.6 源码仓库【保持原样，不做任何手动修改】。
所有移植改动都由本脚本在 CI 里、克隆完源码之后、编译之前完成。

好处：
  - 源码可以随意换 commit / 换分支，不用维护 fork
  - 上游更新直接改 SOURCE_COMMIT 即可
代价：
  - 依赖正则/锚点定位，上游改动文件格式时可能失配
    → 本脚本对致命项（DTS、机型注册、MAC）严格失败，
      对非致命项（sysupgrade）降级为警告，避免误判成编译错误。

用法
────
    python3 scripts/prepare-source.py <源码目录>

做四件事
────────
  1) 复制 DTS                    → target/linux/mediatek/dts/
  2) 追加镜像定义 device.mk      → target/linux/mediatek/image/filogic.mk
  3) 改 02_network               → 接口分组(并入) + MAC(独立分支)
  4) 改 platform.sh              → sysupgrade(独立分支)
  5) 打完补丁后逐条复核，缺哪项报哪项
"""

from pathlib import Path
import re
import shutil
import sys

# ══════════════════════════════════════════════════════════════
# 一、常量区：所有关键数字集中在这里，改一处即可
# ══════════════════════════════════════════════════════════════

# ── 分区布局：114MiB（对应 hanwckf 系 U-Boot 的 expand(114m)）──
# nmbm0:1024k(bl2),512k(u-boot-env),2048k(factory),2048k(fip),116736k(ubi)
# 原 Anser-y 版本是 248MiB(248320k)，这里我们改成 114MiB(116736k)。
MTDPARTS_KIB = (1024, 512, 2048, 2048, 116736)
MTDPARTS_TOTAL = 0x07780000                 # = sum(MTDPARTS_KIB) * 1024
MTDPARTS_STR = (
    "mtdparts=nmbm0:1024k(bl2),512k(u-boot-env),2048k(factory),"
    "2048k(fip),116736k(ubi)"
)

# DTS / device.mk 里必须出现的数值（用于事后复核）
UBI_REG = "reg = <0x0580000 0x07200000>;"   # ubi 分区: 起始 0x580000 + 长度 114MiB
IMAGE_SIZE = "IMAGE_SIZE := 115712k"        # = 116736k - 1MiB，留给 NMBM/UBI 开销

# ══════════════════════════════════════════════════════════════
# MAC：【按偏移动态推算】，不再硬编码
# ────────────────────────────────────────────────────────────
# 为什么改：硬编码会把本机 MAC 写死进固件，别人刷了就跟你撞 MAC。
# 改成从每台机器自己的 factory 分区读出基准，再按增量推算 —— 通用。
#
# 实测（本机）：
#   factory 0x04 = 48:DA:35:50:70:F7   ← 2.4G，作为基准
#   factory 0x0a = 48:DA:35:50:70:F8   ← 5G（由无线驱动直接读，这里不参与）
#   机身标签     = 48:DA:35:50:70:F5
#
# 推算规则（基准 = 2.4G = F7）：
#   LAN = 基准 - 1   →  F7 - 1 = F6
#   WAN = 基准 - 2   →  F7 - 2 = F5
#
# ⚠️ 若你的机器布局不同，只改下面三个数字即可，不用动任何代码逻辑。
# ══════════════════════════════════════════════════════════════
MAC_BASE_OFFSET = 4     # factory 分区内偏移（十进制 4 = 十六进制 0x04）：2.4G MAC
MAC_LAN_DELTA = -1      # LAN  = 基准 - 1
MAC_WAN_DELTA = -2      # WAN  = 基准 - 2

# ── 锚点机型：补丁插入位置的参照物 ──────────────────────────
# 选 360T7 是因为它与 WF3000A 同为 MT7531 交换机 + 4 个千兆口，
# 且它的接口配置串与我们的 DTS 完全一致（见下）。
ANCHOR = "qihoo,360t7"

# ── 接口分组：并入 360T7 那一组（共用动作串）────────────────
# 共用的是这行纯数据，与我们 DTS 的 lan1/lan2/lan3/wan 一字不差：
#   ucidef_set_interfaces_lan_wan "lan1 lan2 lan3" wan
# 因为只是数据，共用完全等价，所以用「续行并入」最省事。
EXPECT_IFACE_ACTION = 'ucidef_set_interfaces_lan_wan "lan1 lan2 lan3" wan'

# ── 是否给 platform.sh 打补丁（False = 只保留 U-Boot Web 刷机）──
ENABLE_SYSUPGRADE = True

# ── sysupgrade 分支里是否显式声明三个 UBI 卷设置 ────────────
# 依据：DTS 里 UBI 分区 label = "ubi"；
#       device.mk 里 KERNEL_IN_UBI := 1 → 生成 kernel / rootfs 卷。
# 与 360T7 那组的值一致，显式写出来更明确。
SET_CI_PARTS = True

# ══════════════════════════════════════════════════════════════
# 一b、无线常量（★ 决定固件有没有 WiFi）
# ══════════════════════════════════════════════════════════════
#
# ⚠️ 致命前提：这份源码【没有】开源 mt76 驱动（package/kernel/mt76 不存在）。
#    filogic.mk 里那 104 处 kmod-mt7915e / 70 处 kmod-mt7981-firmware /
#    mt7981-wo-firmware 是上游 immortalwrt 的【死引用】——包根本不存在，
#    写进 .config 会被 make defconfig 静默丢弃，编译照常成功但固件没有 WiFi。
#    这正是之前「能刷机能上网但没有无线」的根因。
#
# 本源码真实可用的无线是源码自带的 MTK 闭源驱动：
WIRELESS_PKGS = (
    "package/mtk/drivers/mt_wifi",          # kmod-mt_wifi     → mt_wifi.ko
    "package/mtk/drivers/warp",             # kmod-warp        → WED 硬件卸载
    "package/mtk/drivers/conninfra",        # kmod-conninfra   → 连接基础设施
    "package/mtk/drivers/wifi-profile",     # wifi-dats        → l1profile/*.dat
    "package/mtk/applications/mtwifi-cfg",  # mtwifi-cfg       → 无线配置工具
)
# device.mk 的 DEVICE_PACKAGES 必须带出的包名
WIRELESS_DEVICE_PKGS = (
    "kmod-mt_wifi", "kmod-warp", "kmod-conninfra", "wifi-dats", "mtwifi-cfg",
)

# ── EEPROM 偏移：本机 = 0x0 ──────────────────────────────────
# 【为什么必须改 config.in 而不是写 .config】
#   package/mtk/drivers/mt_wifi/config.in 里它是【无 prompt】的 hex 符号：
#       config  MTK_RT_FIRST_IF_RF_OFFSET
#               hex
#               depends on ! MTK_FIRST_IF_NONE
#               default 0xc0000          ← 别家主板的残留值
#   Kconfig 对无 prompt 的符号【不保留】用户在 .config 里的赋值，
#   make defconfig 每次都会把它重置回 default。
#   ⇒ 在 .config 写 CONFIG_MTK_RT_FIRST_IF_RF_OFFSET=0x0 是无效的，
#     这正是上一次 CI 报「make defconfig 后缺少必需项」的根因。
#   ⇒ 唯一可靠做法：改 config.in 的 default。
#
# 【0x0 的两条独立依据】
#   A 实机：hexdump -C -n 128 /dev/mtd2
#     0x00 = 81 79 → 小端 u16 = 0x7981 = MT7981 chipid（驱动正是这么校验）
#     0x04 = 48:DA:35:50:70:F7 (2.4G MAC)
#     0x0a = 48:DA:35:50:70:F8 (5G  MAC)
#   B 源码：package/mtk/drivers/wifi-profile/files/mt7981/l1profile.dat
#     INDEX0_EEPROM_offset=0x0
EEPROM_OFFSET_OLD = "0xc0000"
EEPROM_OFFSET_NEW = "0x0"
MT_WIFI_CONFIG_IN = "package/mtk/drivers/mt_wifi/config.in"
MT_WIFI_EEPROM_SYMBOL = "MTK_RT_FIRST_IF_RF_OFFSET"

# 是否启用动作5（改 config.in 的 default）
# ⚠️ 默认 False —— 实测把 default 从 0xc0000 改成 0x0 会导致闭源驱动编译失败：
#      mt_wifi/embedded/common/eeprom.c: error: 'A32_RT2_OFFSET' undeclared
#      make[6]: *** [scripts/Makefile.build:243: .../embedded/common/eeprom.o] Error 1
#      ERROR: package/mtk/drivers/mt_wifi failed to build.
#    0xc0000 是官方 defconfig 验证过的值。闭源驱动里 EEPROM 分区布局相关的
#    内部符号（A32_RT2_OFFSET 等）只在官方默认代码路径下才有定义，
#    改成本机的 0x0 会走进另一条分支，引用到未定义的符号。
#
# 【那本机 EEPROM 偏移 0x0 怎么保证？】
#    不靠编译期宏，靠【运行期覆盖】：
#      package/mtk/drivers/wifi-profile/files/mt7981/l1profile.dat
#        INDEX0_EEPROM_offset=0x0
#      rt_profile.c 的 l1set_eeprom_offset() 解析该 .dat 写入
#      l1profile[dev_idx].ee_info.offset；get_dev_eeprom_offset() 返回它；
#      最终 RtmpFlashRead(..., get_dev_eeprom_offset(pAd), ...) 用它读 flash。
#    ⇒ 编译期 0xc0000，运行期实际按 0x0 读 —— 效果等价，且避开编译雷区。
PATCH_EEPROM_OFFSET = False

# ── MT7981 固件与默认 EEPROM（安全阀）────────────────────────
# 驱动加载需要这些 bin；即便 EEPROM 读取失败也会回退到默认 EEPROM，
# 于是 WiFi 照样能起来（只是用通用校准值）。
MT7981_FW_DIR = "package/mtk/drivers/mt_wifi/files/mt7981-fw-20240613"
MT7981_FW_FILES = ("WIFI_RAM_CODE_MT7981.bin",
                   "7981_WACPU_RAM_CODE_release.bin",
                   "mt7981_patch_e1_hdr.bin")
MT7981_EEPROM_DIR = "package/mtk/drivers/mt_wifi/files/mt7981-default-eeprom"

# ── l1profile.dat（★ v6 方案的核心：运行期把 EEPROM 偏移覆盖为 0x0）──
# 安装链路（已核对 package/mtk/drivers/wifi-profile/Makefile）：
#   if [ "$(CONFIG_first_card_name)" = "MT7981" ]; then
#       $(INSTALL_DATA) ./files/mt7981/* $(1)/etc/wireless/mediatek/
#   ...
#   mv $(1)/etc/wireless/mediatek/l1profile.dat $(1)/etc/wireless/l1profile.dat
# ⇒ 只有 CONFIG_first_card_name="MT7981" 时 mt7981/l1profile.dat 才会被装上。
L1PROFILE_SRC = "package/mtk/drivers/wifi-profile/files/mt7981/l1profile.dat"
L1PROFILE_KEY = "INDEX0_EEPROM_offset=0x0"
# config 里必须有的符号（决定 l1profile.dat 是否安装）
FIRST_CARD_NAME_SYMBOLS = ('CONFIG_first_card=y', 'CONFIG_first_card_name="MT7981"')
# factory 分区标签：驱动 mt_mtd_read_nm_wifi() 先找 "Factory"，失败再找 "factory"
FACTORY_LABEL = "factory"


# ══════════════════════════════════════════════════════════════
# 二、通用工具：shell case 语句的定位与插入
# ══════════════════════════════════════════════════════════════

def find_function(lines, name):
    """定位 shell 函数 `name()` 的行范围。

    兼容两种写法：
        platform_do_upgrade() {      ← 花括号同行
        mediatek_setup_macs()        ← 花括号在下一行
        {
    返回 (起始行, 结束行)，结束行是顶格的那个 `}`。
    """
    pat = re.compile(rf"^{re.escape(name)}\s*\(\)")
    for i, ln in enumerate(lines):
        if pat.match(ln.rstrip()):
            j = i + 1
            while j < len(lines):
                if lines[j].rstrip() == "}":
                    return i, j
                j += 1
            return i, len(lines) - 1
    return None


def backtrack_group(lines, idx):
    """从 case pattern 组中的某一行回溯到该组的【第一行】。

    case 的一个 pattern 组形如：
        asus,rt-ax52|\            ← 续行，以 |\\ 结尾
        qihoo,360t7|\
        routerich,ax3000-ubootmod)   ← 组结束

    只要上一行以 `|\\` 结尾就继续上移，最终停在组首。

    ⚠️ 这是关键：插入点必须是【组首之前】。
       在续行链中间插入内容会打断链路，
       导致相邻机型（如 asus,rt-ax52）也被并进我们的分支。
    """
    i = idx
    while i > 0 and lines[i - 1].rstrip().endswith("|\\"):
        i -= 1
    return i


def find_anchor_groups(lines, lo, hi, anchor):
    """在 [lo, hi) 行范围内，找出 anchor 作为 case pattern 出现的所有组首行号。

    同时兼容两种行尾：
        qihoo,360t7)       单独成组
        qihoo,360t7|\\      续行形式
    """
    pat = re.compile(rf"^\s*{re.escape(anchor)}\s*(\)|\|\\)$")
    hits = [i for i in range(lo, hi) if pat.match(lines[i].rstrip())]
    # 去重：同一个组可能被多个 pattern 命中
    return sorted({backtrack_group(lines, i) for i in hits})


def insert_before(lines, starts, block):
    """在多个位置前插入 block。从下往上插，避免行号漂移。"""
    for s in sorted(starts, reverse=True):
        lines[s:s] = block
    return len(starts)


def indent_of(line):
    m = re.match(r"^(\s*)", line)
    return m.group(1) if m else ""


# ══════════════════════════════════════════════════════════════
# 三、四个补丁动作
# ══════════════════════════════════════════════════════════════

def patch_dts(source, custom, log):
    """动作 1：复制设备树。

    DTS 决定了：分区表、交换机端口、GPIO(LED/按键)、MAC nvmem 偏移、无线校准来源。
    写错分区 → 内核找不到 UBI 卷，起不来。
    """
    dst = source / "target/linux/mediatek/dts/mt7981b-kst-wf3000a.dts"
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(custom / "mt7981b-kst-wf3000a.dts", dst)
    log("动作1", f"DTS 已复制 → {dst.relative_to(source)}")


def patch_image_mk(source, custom, log):
    """动作 2：把机型定义追加到 filogic.mk。

    这一步【最关键】——它让 config 符号 CONFIG_TARGET_mediatek_filogic_DEVICE_kst_wf3000a
    得以存在。没有它，.config 里写这个符号会被 make defconfig 静默丢弃。

    必须【追加】而不是覆盖，否则会丢掉上游所有其他机型。
    """
    mk = source / "target/linux/mediatek/image/filogic.mk"
    text = mk.read_text(encoding="utf-8")

    if "define Device/kst_wf3000a" in text:
        # 幂等保护：重复追加会导致 make 报重复定义
        raise RuntimeError(
            "filogic.mk 里已存在 kst_wf3000a 定义。"
            "若源码已内置该机型，请先核对它的分区布局是不是 114MiB 再决定是否跳过本步骤。"
        )

    fragment = (custom / "device.mk").read_text(encoding="utf-8")
    mk.write_text(text.rstrip("\n") + "\n\n" + fragment, encoding="utf-8", newline="\n")
    log("动作2", f"镜像定义已追加 → {mk.relative_to(source)}")


def patch_02_network(source, log):
    """动作 3：改网络配置脚本（两处，性质不同）。

    ── 3a 接口分组：并入 360T7（续行形式）──────────────────
    共用的是【纯数据】：ucidef_set_interfaces_lan_wan "lan1 lan2 lan3" wan
    与我们 DTS 的端口定义完全一致，共用等价，零风险。
    为什么必须加：默认分支 `*)` 给的是 "lan1 lan2 lan3 lan4" wan，
    引用了不存在的 lan4，会导致 LAN 桥接起不来。

    ── 3b MAC：独立分支（按偏移动态推算）──────────────────
    不能并入，因为 360T7 那行是【读取逻辑】：
        lan_mac=$(mtd_get_mac_ascii factory lanMac)
    我们的 factory 是二进制布局（0x4=F7 / 0xa=F8），没有 lanMac 这个 ASCII key，
    读出来是空值 → 不设置任何 MAC → 回退到内核值（就是原先 MAC 不对的问题）。
    所以必须自己写分支。

    写法：
        base_mac=$(mtd_get_mac_binary factory 4)   ← 读 2.4G MAC 作基准
        lan_mac=$(macaddr_add "$base_mac" -2)      ← LAN = 基准 - 2
        wan_mac=$(macaddr_add "$base_mac" -1)      ← WAN = 基准 - 1
    每台机器读自己的 flash，不会撞 MAC。

    【为什么用 -2 而不是 macaddr_sub】
    源码 package/base-files/files/lib/functions/system.sh 里只有 macaddr_add，
    没有 macaddr_sub。macaddr_add 的实现是
        $((0x${nic//:/} + val & 0xffffff))
    传负数可以正常做减法（0x5070f7 + -2 = 0x5070f5），已按实现推演验证。
    """
    f = source / "target/linux/mediatek/filogic/base-files/etc/board.d/02_network"
    if not f.is_file():
        raise FileNotFoundError(f)

    lines = f.read_text(encoding="utf-8").split("\n")

    # ── 3a 接口分组 ──
    rng = find_function(lines, "mediatek_setup_interfaces")
    if not rng:
        raise RuntimeError("02_network 里找不到 mediatek_setup_interfaces()")
    lo, hi = rng
    starts = find_anchor_groups(lines, lo, hi, ANCHOR)
    if not starts:
        raise RuntimeError(
            f"mediatek_setup_interfaces() 里找不到锚点 {ANCHOR}，无法定位接口分组。"
            "上游文件可能已改版，请人工核对。"
        )
    ind = indent_of(lines[starts[0]])
    # 续行并入：只加一行 kst,wf3000a|\
    n_iface = insert_before(lines, starts, [f"{ind}kst,wf3000a|\\"])

    # ── 3b MAC 分支 ──
    # 注意：3a 插入后行号变了，必须重新定位函数
    lines = "\n".join(lines).split("\n")
    rng = find_function(lines, "mediatek_setup_macs")
    if not rng:
        raise RuntimeError("02_network 里找不到 mediatek_setup_macs()")
    lo, hi = rng
    starts = find_anchor_groups(lines, lo, hi, ANCHOR)
    if not starts:
        raise RuntimeError(
            f"mediatek_setup_macs() 里找不到锚点 {ANCHOR}，无法定位 MAC 分支位置。"
        )
    ind = indent_of(lines[starts[0]])
    # 独立分支：插在 360T7 组【之前】
    block = [
        f"{ind}kst,wf3000a)",
        f'{ind}\tbase_mac=$(mtd_get_mac_binary factory {MAC_BASE_OFFSET})',
        f'{ind}\tlan_mac=$(macaddr_add "$base_mac" {MAC_LAN_DELTA})',
        f'{ind}\twan_mac=$(macaddr_add "$base_mac" {MAC_WAN_DELTA})',
        f"{ind}\tlabel_mac=$lan_mac",
        f"{ind}\t;;",
    ]
    n_mac = insert_before(lines, starts, block)

    f.write_text("\n".join(lines), encoding="utf-8", newline="\n")
    log("动作3", f"02_network 已改：接口分组 {n_iface} 处 + MAC 分支 {n_mac} 处")


def patch_platform_sh(source, log):
    """动作 4：打通 sysupgrade。

    在 padavanonly 6.6 这份 platform.sh 里，360T7 只出现在 platform_do_upgrade()
    一个函数中；platform_check_image() 里没有机型分支，走通用 `*)` 的
    nand_do_platform_check，已覆盖我们，无需补丁。

    本脚本不写死"必须补几处"，而是数 ANCHOR 出现几次就补几次，
    这样上游改版也不会误判。
    """
    f = source / "target/linux/mediatek/filogic/base-files/lib/upgrade/platform.sh"
    if not f.is_file():
        raise FileNotFoundError(f)

    lines = f.read_text(encoding="utf-8").split("\n")

    # ⚠️ 必须【逐个函数重新定位】，不能先把位置全算出来再统一插。
    # 原因：第一次插入会让后续行号整体下移，若沿用旧行号，
    #       第二次插入会落在错误位置（实测会插到 esac 之后、case 之外 →
    #       sh -n 直接报 Syntax error）。
    # 这与 patch_02_network() 里"3a 插完必须重新定位"是同一个坑。
    #
    # 当前 padavanonly 6.6 的真实 platform.sh 里，ANCHOR 只出现在
    # platform_do_upgrade() 一个函数中（platform_check_image() 走通用 `*)`），
    # 所以实际只会命中 1 处。但上游若某天在 check_image 里也加了分支，
    # 这段必须能正确工作 —— 故按"每次重新定位"实现。
    fnames = ("platform_check_image", "platform_do_upgrade")
    total = 0
    for fname in fnames:
        # 每次都基于【当前最新的 lines】重新定位（关键）
        rng = find_function(lines, fname)
        if not rng:
            continue
        lo, hi = rng
        starts = find_anchor_groups(lines, lo, hi, ANCHOR)
        if not starts:
            continue
        ind = indent_of(lines[starts[0]])
        if not ENABLE_SYSUPGRADE:
            continue
        block = [f"{ind}kst,wf3000a)"]
        if SET_CI_PARTS:
            block += [
                f'{ind}\tCI_UBIPART="ubi"',
                f'{ind}\tCI_KERNPART="kernel"',
                f'{ind}\tCI_ROOTPART="rootfs"',
            ]
        block += [f'{ind}\tnand_do_upgrade "$1"', f"{ind}\t;;"]
        total += insert_before(lines, starts, block)

    if total == 0:
        # 非致命：只是没有 sysupgrade，U-Boot Web 刷机不受影响
        print("::warning::platform.sh 里未找到锚点，跳过 sysupgrade 补丁。"
              "仍可用 U-Boot Web 上传 factory.bin 刷机。")
        return 0

    f.write_text("\n".join(lines), encoding="utf-8", newline="\n")
    log("动作4", f"platform.sh 已改：sysupgrade 分支 {total} 处")
    return total


def patch_eeprom_offset(source, log):
    """动作 5：把 MTK 闭源驱动的 EEPROM 偏移默认值改成本机的 0x0。

    ── 为什么必须改源码而不写 .config ──────────────────────
    config.in 里 MTK_RT_FIRST_IF_RF_OFFSET 是【无 prompt】的 hex 符号：

        config  MTK_RT_FIRST_IF_RF_OFFSET
                hex
                depends on ! MTK_FIRST_IF_NONE
                default 0xc0000        ← 别家主板的残留值

    Kconfig 规则：无 prompt 的符号用户不可设置，make defconfig 重新解析时
    会【丢弃 .config 里的赋值、重置为 default】。
    ⇒ 在 .config 里写 CONFIG_MTK_RT_FIRST_IF_RF_OFFSET=0x0 永远无效，
      这也是上一次 CI 报「make defconfig 后缺少必需项」的唯一原因
      （同期其他带值符号都恰好 default 一致才幸存）。
    ⇒ 唯一可靠的根治办法就是改这里的 default。

    ── 幂等 ────────────────────────────────────────────────
    已经是目标值就直接跳过，重复运行不会叠加。
    """
    if not PATCH_EEPROM_OFFSET:
        log("动作5", "已停用（PATCH_EEPROM_OFFSET=False）")
        log("动作5", "编译期保持官方 0xc0000，避开 eeprom.c 的 A32_RT2_OFFSET 编译错误")
        log("动作5", "运行期由 l1profile.dat 的 INDEX0_EEPROM_offset=0x0 覆盖")
        return 0

    f = source / MT_WIFI_CONFIG_IN
    if not f.is_file():
        raise FileNotFoundError(f"找不到 {MT_WIFI_CONFIG_IN}，无线方案可能已变更")

    text = f.read_text(encoding="utf-8")
    lines = text.split("\n")

    # 定位 config 块：从 "config  SYMBOL" 起到下一个 "config " 或文件末尾
    pat = re.compile(rf"^\s*config\s+{re.escape(MT_WIFI_EEPROM_SYMBOL)}\s*$")
    start = None
    for i, ln in enumerate(lines):
        if pat.match(ln):
            start = i
            break
    if start is None:
        raise RuntimeError(
            f"{MT_WIFI_CONFIG_IN} 里找不到 config {MT_WIFI_EEPROM_SYMBOL}，"
            "上游文件可能已改版，请人工核对。"
        )

    end = len(lines)
    for j in range(start + 1, len(lines)):
        if re.match(r"^\s*config\s+\S", lines[j]):
            end = j
            break

    block = lines[start:end]
    # 在该块内把 default 的旧值换成新值
    changed = 0
    for i in range(len(block)):
        m = re.match(r"^(\s*default\s+)" + re.escape(EEPROM_OFFSET_OLD) + r"\s*$",
                     block[i])
        if m:
            block[i] = m.group(1) + EEPROM_OFFSET_NEW
            changed += 1

    if changed == 0:
        # 可能已经是目标值（幂等），也可能格式变了
        cur = "\n".join(block)
        if re.search(r"^\s*default\s+" + re.escape(EEPROM_OFFSET_NEW) + r"\s*$",
                     cur, re.M):
            log("动作5", f"EEPROM 偏移 default 已是 {EEPROM_OFFSET_NEW}，跳过")
            return 0
        raise RuntimeError(
            f"{MT_WIFI_CONFIG_IN} 的 {MT_WIFI_EEPROM_SYMBOL} 块里找不到 "
            f"'default {EEPROM_OFFSET_OLD}'（也没找到已改好的 "
            f"'default {EEPROM_OFFSET_NEW}'）。上游格式可能已变，请人工核对：\n"
            + "\n".join(block)
        )

    lines[start:end] = block
    f.write_text("\n".join(lines), encoding="utf-8", newline="\n")
    log("动作5", f"{MT_WIFI_CONFIG_IN}: {MT_WIFI_EEPROM_SYMBOL} default "
                 f"{EEPROM_OFFSET_OLD} → {EEPROM_OFFSET_NEW}（{changed} 处）")
    return changed


# ══════════════════════════════════════════════════════════════
# 四、打完补丁后复核
# ══════════════════════════════════════════════════════════════

def verify(source):
    """逐条复核，缺哪项报哪项。致命项返回 False 让 workflow 失败。"""
    print("\n── 复核 ──────────────────────────────────────────")
    failed = []

    def chk(cond, name, detail=""):
        # 返回 cond，便于用 `if chk(...)` 做「父项通过才查子项」的嵌套
        if cond:
            print(f"  [OK]   {name}" + (f"  ({detail})" if detail else ""))
        else:
            failed.append(name)
            print(f"  [FAIL] {name}" + (f"  ({detail})" if detail else ""))
        return cond

    # 1) DTS
    dts = source / "target/linux/mediatek/dts/mt7981b-kst-wf3000a.dts"
    if chk(dts.is_file(), "DTS 存在"):
        t = dts.read_text(encoding="utf-8")
        chk(UBI_REG in t, "DTS 分区为 114MiB", UBI_REG)
        chk('compatible = "kst,wf3000a"' in t, "DTS compatible 正确(必须小写)")
        chk("mediatek,nmbm" in t, "NMBM 已启用")

    # 2) filogic.mk
    mk = source / "target/linux/mediatek/image/filogic.mk"
    t = mk.read_text(encoding="utf-8") if mk.is_file() else ""
    chk("define Device/kst_wf3000a" in t, "机型已注册")
    chk(IMAGE_SIZE in t, "IMAGE_SIZE = 115712k")
    chk("TARGET_DEVICES += kst_wf3000a" in t, "TARGET_DEVICES 已追加")

    # 3) 02_network
    f = source / "target/linux/mediatek/filogic/base-files/etc/board.d/02_network"
    t = f.read_text(encoding="utf-8") if f.is_file() else ""
    chk("kst,wf3000a|\\" in t, "接口分组已并入(续行)")
    chk(EXPECT_IFACE_ACTION in t, "接口动作串正确", EXPECT_IFACE_ACTION)
    # 不再校验硬编码值（那样会把本机 MAC 写死），改为校验推算逻辑三要素
    chk("mtd_get_mac_binary factory %d" % MAC_BASE_OFFSET in t,
        "MAC 基准读取已写入", f"factory 偏移 {MAC_BASE_OFFSET}")
    chk(f'macaddr_add "$base_mac" {MAC_LAN_DELTA}' in t,
        "LAN 推算已写入", f"基准 {MAC_LAN_DELTA:+d}")
    chk(f'macaddr_add "$base_mac" {MAC_WAN_DELTA}' in t,
        "WAN 推算已写入", f"基准 {MAC_WAN_DELTA:+d}")

    # 4) platform.sh（非致命）
    f = source / "target/linux/mediatek/filogic/base-files/lib/upgrade/platform.sh"
    t = f.read_text(encoding="utf-8") if f.is_file() else ""
    if "kst,wf3000a" in t:
        print("  [OK]   sysupgrade 分支已写入")
    else:
        print("  [warn] sysupgrade 未打通（不影响 U-Boot Web 刷机）")

    # 5) 无线（★ 决定固件有没有 WiFi，全部为致命项）
    print("  ── 无线 ──")
    for rel in WIRELESS_PKGS:
        chk((source / rel).is_dir(), f"无线包存在 {rel.split('/')[-1]}")

    if (source / "package/kernel/mt76").is_dir():
        print("  [warn] 检测到 package/kernel/mt76 —— 本方案的取包方式需重新评估")
    else:
        print("  [OK]   无开源 mt76（符合预期：走 MTK 闭源驱动）")

    fw_dir = source / MT7981_FW_DIR
    if chk(fw_dir.is_dir(), "MT7981 固件目录存在", MT7981_FW_DIR.split("/")[-1]):
        names = {p.name for p in fw_dir.iterdir()} if fw_dir.is_dir() else set()
        for n in MT7981_FW_FILES:
            chk(n in names, f"固件 {n}")

    if chk((source / MT7981_EEPROM_DIR).is_dir(), "默认 EEPROM 存在（安全阀）"):
        pass

    # device.mk 的 DEVICE_PACKAGES 必须带出无线包
    mk = source / "target/linux/mediatek/image/filogic.mk"
    t = mk.read_text(encoding="utf-8") if mk.is_file() else ""
    m = re.search(r"^define Device/kst_wf3000a$.*?^endef$", t, re.M | re.S)
    dev_block = m.group(0) if m else ""
    for pkg in WIRELESS_DEVICE_PKGS:
        chk(pkg in dev_block, f"DEVICE_PACKAGES 含 {pkg}")

    # config.in 的 EEPROM 偏移 default 是否已改
    ci = source / MT_WIFI_CONFIG_IN
    t_ci = ci.read_text(encoding="utf-8") if ci.is_file() else ""
    blk = ""
    mm = re.search(rf"^\s*config\s+{re.escape(MT_WIFI_EEPROM_SYMBOL)}\s*$.*?(?=^\s*config\s|\Z)",
                   t_ci, re.M | re.S)
    if mm:
        blk = mm.group(0)
    # 非致命：只打印，不要求等于 0x0（编译期改动会触发闭源驱动编译错误）
    m_def = re.search(r"^\s*default\s+(\S+)\s*$", blk, re.M)
    def_val = m_def.group(1) if m_def else "（未找到）"
    if PATCH_EEPROM_OFFSET:
        chk(def_val == EEPROM_OFFSET_NEW,
            f"EEPROM 偏移 default = {EEPROM_OFFSET_NEW}", f"实际 {def_val}")
    else:
        print(f"  [info] 编译期 EEPROM 偏移 default = {def_val}（官方值，未改动）")
        print(f"         → 运行期由 l1profile.dat 覆盖为 {EEPROM_OFFSET_NEW}")

    # l1profile.dat：★ v6 方案的核心 —— 运行期把 EEPROM 偏移覆盖为 0x0
    lp = source / L1PROFILE_SRC
    t_lp = lp.read_text(encoding="utf-8") if lp.is_file() else ""
    chk(lp.is_file(), "l1profile.dat 存在（运行期覆盖偏移）")
    chk(L1PROFILE_KEY in t_lp,
        f"l1profile.dat 含 {L1PROFILE_KEY}")

    # config 里必须有 first_card_name="MT7981"，否则上面的 .dat 根本不会被安装
    cfg = source.parent  # 占位，实际从环境变量取不到就用默认路径
    cfg_path = Path(__file__).resolve().parents[1] / "config" / "wf3000a.config"
    t_cfg = cfg_path.read_text(encoding="utf-8") if cfg_path.is_file() else ""
    for sym in FIRST_CARD_NAME_SYMBOLS:
        chk(sym in t_cfg, f'config 含 {sym}（决定 l1profile.dat 是否安装）')

    # DTS 的 factory 分区标签：驱动先找 "Factory" 再找 "factory"
    dts_t = dts.read_text(encoding="utf-8") if dts.is_file() else ""
    chk(f'label = "{FACTORY_LABEL}"' in dts_t, f"DTS factory 标签 = {FACTORY_LABEL}")
    chk('&wifi' in dts_t and 'status = "okay"' in dts_t, "DTS &wifi 已启用")

    # 6) 算术
    total = sum(MTDPARTS_KIB) * 1024
    chk(total == MTDPARTS_TOTAL, "分区和 == 总地址空间",
        f"{sum(MTDPARTS_KIB)} KiB -> {hex(total)}")
    chk(MTDPARTS_KIB[-1] - 1024 == 115712, "IMAGE_SIZE == ubi - 1MiB")

    print("──────────────────────────────────────────────────")
    if failed:
        print(f"::error:: {len(failed)} 项未通过: {', '.join(failed)}")
        return False
    print("复核全部通过")
    return True


# ══════════════════════════════════════════════════════════════
# 五、主流程
# ══════════════════════════════════════════════════════════════

def main():
    if len(sys.argv) != 2:
        raise SystemExit("usage: prepare-source.py OPENWRT_SOURCE_DIR")

    source = Path(sys.argv[1]).resolve()
    custom = Path(__file__).resolve().parents[1] / "custom" / "wf3000a"

    if not source.is_dir():
        raise SystemExit(f"源码目录不存在: {source}")

    print("=" * 66)
    print("WF3000A 板级移植 —— 构建时打补丁")
    print(f"源码: {source}")
    print("=" * 66)

    def log(tag, msg):
        print(f"  {tag}: {msg}")

    patch_dts(source, custom, log)
    patch_image_mk(source, custom, log)
    patch_02_network(source, log)
    if ENABLE_SYSUPGRADE:
        patch_platform_sh(source, log)
    else:
        print("  （ENABLE_SYSUPGRADE=False，跳过 platform.sh 补丁）")
    patch_eeprom_offset(source, log)

    print(f"\n布局: {MTDPARTS_STR}")
    print(f"MAC : 基准=factory 偏移 {MAC_BASE_OFFSET}（2.4G） "
          f"LAN=基准{MAC_LAN_DELTA:+d}  WAN=基准{MAC_WAN_DELTA:+d}")
    print("      每台机器读自己的 flash，不会与他人撞 MAC")

    if not verify(source):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
