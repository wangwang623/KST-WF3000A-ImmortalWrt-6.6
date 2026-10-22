#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
本地模拟运行 —— 不需要 GitHub Actions、不需要真的编译。

模拟内容：
  1) 静态语法校验（python / yaml / shell / config 格式）
  2) ★ EEPROM 偏移补丁测试（复现并验证上次 CI 失败的根因）
  3) 建一棵「未打补丁」的模拟源码树 + 跑 prepare-source.py
  4) 模拟 make defconfig 的符号解析 + workflow 的硬/软校验
  5) 幂等性检查
  6) 汇总

用法：
    python3 scripts/simulate.py

═══════════════════════════════════════════════════════════════
★ 关于第 4 步的 defconfig 模拟（本脚本最重要的修正）
───────────────────────────────────────────────────────────────
旧版 defconfig() 对【所有非 PACKAGE / 非 DEVICE 符号】一律无条件保留：

    else:
        kept.append(s)          # ← 掩盖了真实的重置行为

于是本地模拟「全部通过」，真实 CI 却失败在
    make defconfig 后缺少必需项: CONFIG_MTK_RT_FIRST_IF_RF_OFFSET=0x0

真实原因是 Kconfig 规则：MTK_RT_FIRST_IF_RF_OFFSET 是【无 prompt】
的 hex 符号，用户在 .config 里的赋值不被保留，每次 defconfig 都重置
为 default。所以模拟必须体现这一条，否则恒为假阳性。
═══════════════════════════════════════════════════════════════
"""

import subprocess
import sys
import shutil
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PASS, FAIL = [], []


def step(name):
    print(f"\n{'='*68}\n▶ {name}\n{'='*68}")


def chk(cond, name, detail=""):
    tag = "OK  " if cond else "FAIL"
    print(f"  [{tag}] {name}" + (f"  ({detail})" if detail else ""))
    (PASS if cond else FAIL).append(name)
    return cond


def run(cmd, **kw):
    return subprocess.run(cmd, shell=isinstance(cmd, str), capture_output=True,
                          text=True, **kw)


# ══════════════════════════════════════════════════════════════
# 1. 静态语法校验
# ══════════════════════════════════════════════════════════════
step("1. 静态语法校验")

r = run([sys.executable, "-m", "py_compile", str(ROOT / "scripts/prepare-source.py")])
chk(r.returncode == 0, "prepare-source.py 语法正确", r.stderr.strip()[:80])

try:
    import yaml
    yaml.safe_load((ROOT / ".github/workflows/build.yml").read_text())
    chk(True, "build.yml YAML 正确")
except Exception as e:
    chk(False, "build.yml YAML 正确", str(e))

cfg_lines = (ROOT / "defconfig/wf3000a.config").read_text().split("\n")
syms = [l.split("=")[0] for l in cfg_lines
        if l.startswith("CONFIG_") and not l.startswith("#")]
dup = {s for s in syms if syms.count(s) > 1}
chk(not dup, "config 无重复符号", str(dup) if dup else "")
bad = [l for l in cfg_lines
       if l.strip() and not l.startswith("#") and not l.startswith("CONFIG_")]
chk(not bad, "config 无非法行", str(bad) if bad else "")


# ══════════════════════════════════════════════════════════════
# 2. ★ EEPROM 偏移补丁测试（不依赖任何外部文件）
# ══════════════════════════════════════════════════════════════
step("2. EEPROM 偏移补丁逻辑测试（默认停用，仅验证代码正确性）")

# 模拟上游 config.in 的真实片段（无 prompt 的 hex 符号）
FAKE_CONFIG_IN = "\n".join([
    "config  MTK_RT_FIRST_IF_RF_OFFSET",
    "\thex",
    "\tdepends on ! MTK_FIRST_IF_NONE",
    "\tdefault 0xc0000",
    "",
    "config  MTK_RT_SECOND_IF_RF_OFFSET",
    "\thex",
    "\tdepends on ! MTK_FIRST_IF_NONE",
    "\tdefault 0xc8000",
    "",
])

import importlib.util
_spec = importlib.util.spec_from_file_location("ps", ROOT / "scripts/prepare-source.py")
ps = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ps)

tmp_cfg = Path(tempfile.mkdtemp(prefix="wf3000a-cfg-"))
fake = tmp_cfg / "package/mtk/drivers/mt_wifi"
fake.mkdir(parents=True)
(fake / "config.in").write_text(FAKE_CONFIG_IN)

# 动作5 默认停用（PATCH_EEPROM_OFFSET=False），先验证「停用时不改动」
n_off = ps.patch_eeprom_offset(tmp_cfg, lambda a, b: print(f"    {a}: {b}"))
chk(n_off == 0, "默认停用时不改动 config.in", str(n_off))

# 临时打开，验证补丁逻辑本身正确（测完立即还原）
ps.PATCH_EEPROM_OFFSET = True
n = ps.patch_eeprom_offset(tmp_cfg, lambda a, b: print(f"    {a}: {b}"))
chk(n == 1, "补丁命中 1 处", str(n))
after = (fake / "config.in").read_text()
chk("default 0x0\n" in after, "default 已改为 0x0")
chk("default 0xc8000" in after, "相邻符号 MTK_RT_SECOND_IF_RF_OFFSET 未被误改")
chk(after.count("default 0x0") == 1, "只改了目标一处", str(after.count("default 0x0")))

n2 = ps.patch_eeprom_offset(tmp_cfg, lambda a, b: print(f"    {a}: {b}"))
chk(n2 == 0, "重复运行幂等（不再改动）", str(n2))

# 反向验证：若上游格式变了，必须明确报错而不是静默跳过
(fake / "config.in").write_text("config  MTK_RT_FIRST_IF_RF_OFFSET\n\thex\n")
try:
    ps.patch_eeprom_offset(tmp_cfg, lambda a, b: None)
    chk(False, "上游格式异常时明确报错")
except RuntimeError as e:
    chk(True, "上游格式异常时明确报错", str(e).split("\n")[0][:60])
finally:
    ps.PATCH_EEPROM_OFFSET = False   # 还原为默认（停用）

shutil.rmtree(tmp_cfg, ignore_errors=True)


# ══════════════════════════════════════════════════════════════
# 3. 建模拟源码树 + 打补丁
# ══════════════════════════════════════════════════════════════
step("3. 建模拟源码树并运行 prepare-source.py")

# 这两个是【参考文件】：云编译不读它们（prepare-source.py 直接在源码上做插入），
# 只有本模拟脚本会读（用来反推「未打补丁」的上游版本做对照测试）。
missing_ref = [f for f in ("02_network", "platform.sh")
               if not (ROOT / "custom/wf3000a" / f).is_file()]
SKIP_TREE = bool(missing_ref)
if SKIP_TREE:
    print(f"  [提示] 参考文件缺失: {', '.join(missing_ref)}")
    print("         云编译【不需要】它们，仅本模拟脚本的第 3~5 步需要。")
    print("         第 1、2 步已通过（EEPROM 偏移补丁已单独验证）。")
    print("         若要把 3~5 步也跑起来，请把它们放回 custom/wf3000a/ 。")

if not SKIP_TREE:
    for f in ("02_network", "platform.sh"):
        r = run(["sh", "-n", str(ROOT / "custom/wf3000a" / f)])
        chk(r.returncode == 0, f"{f} (参考文件) shell 语法正确")

    tmp = Path(tempfile.mkdtemp(prefix="wf3000a-sim-"))
    src = tmp / "openwrt"
    S = src / "target/linux/mediatek"
    (S / "dts").mkdir(parents=True)
    (S / "image").mkdir(parents=True)
    (S / "filogic/base-files/etc/board.d").mkdir(parents=True)
    (S / "filogic/base-files/lib/upgrade").mkdir(parents=True)
    # 无线包目录（模拟真实源码）
    for rel in ps.WIRELESS_PKGS:
        (src / rel).mkdir(parents=True)
    (src / ps.MT7981_FW_DIR).mkdir(parents=True)
    for n in ps.MT7981_FW_FILES:
        (src / ps.MT7981_FW_DIR / n).write_text("x")
    (src / ps.MT7981_EEPROM_DIR).mkdir(parents=True)
    lp = src / "package/mtk/drivers/wifi-profile/files/mt7981"
    lp.mkdir(parents=True)
    (lp / "l1profile.dat").write_text("INDEX0_EEPROM_offset=0x0\n"
                                      "INDEX0_EEPROM_size=0x5000\n"
                                      "INDEX0_EEPROM_name=e2p\n")
    (src / ps.MT_WIFI_CONFIG_IN).parent.mkdir(parents=True, exist_ok=True)
    (src / ps.MT_WIFI_CONFIG_IN).write_text(FAKE_CONFIG_IN)

    # 上游原版 mtwifi.sh 的最小等价物：只含动作6 依赖的锚点
    # （真实上游 65 行，这里只要锚点齐全就能验证替换与校验逻辑）
    UPSTREAM_MTWIFI_SH = "\n".join([
        '#!/bin/sh',
        '#',
        '# Copyright (C) 2023, hanwckf <hanwckf@vip.qq.com>',
        '#',
        '',
        'append DRIVERS "mtwifi"',
        '',
        'detect_mtwifi() {',
        '\tlocal idx ifname',
        '\tlocal band hwmode htmode htbsscoex ssid dbdc_main channel',
        '\tif [ -d "/sys/module/mt_wifi" ]; then',
        '\t\tdev_list="$(l1util list)"',
        '\t\tfor dev in $dev_list; do',
        '\t\t\tconfig_get type ${dev} type',
        '\t\t\t[ "$type" = "mtwifi" ] || {',
        '\t\t\t\tifname="$(l1util get ${dev} main_ifname)"',
        '\t\t\t\tidx="$(l1util get ${dev} subidx)"',
        '\t\t\t\tif [ $idx -eq 1 ]; then',
        '\t\t\t\t\tband="2g"',
        '\t\t\t\t\tssid="ImmortalWrt-2.4G"',
        '\t\t\t\t\tchannel="auto"',
        '\t\t\t\telse',
        '\t\t\t\t\tband="5g"',
        '\t\t\t\t\tssid="ImmortalWrt-5G"',
        '\t\t\t\t\tchannel="36"',
        '\t\t\t\t\tdbdc_main="0"',
        '\t\t\t\tfi',
        '\t\t\t\tuci -q batch <<-EOF',
        '\t\t\t\t\tset wireless.default_${dev}=wifi-iface',
        '\t\t\t\t\tset wireless.default_${dev}.ssid=${ssid}',
        '\t\t\t\t\tset wireless.default_${dev}.encryption=none',
        'EOF',
        '\t\t\t\tuci -q commit wireless',
        '\t\t\t}',
        '\t\tdone',
        '\tfi',
        '}',
        '',
    ])
    (src / ps.MTWIFI_SH_SRC).parent.mkdir(parents=True, exist_ok=True)
    (src / ps.MTWIFI_SH_SRC).write_text(UPSTREAM_MTWIFI_SH)

    def strip_patched(name):
        lines = (ROOT / "custom/wf3000a" / name).read_text().split("\n")
        out, i = [], 0
        while i < len(lines):
            s = lines[i].strip()
            if s == "kst,wf3000a|\\":
                i += 1
                continue
            if s == "kst,wf3000a)":
                while i < len(lines) and lines[i].strip() != ";;":
                    i += 1
                i += 1
                continue
            out.append(lines[i]); i += 1
        return "\n".join(out)

    (S / "filogic/base-files/etc/board.d/02_network").write_text(strip_patched("02_network"))
    (S / "filogic/base-files/lib/upgrade/platform.sh").write_text(strip_patched("platform.sh"))
    (S / "image/filogic.mk").write_text(
        "define Device/qihoo_360t7\n  DEVICE_VENDOR := Qihoo\nendef\n"
        "TARGET_DEVICES += qihoo_360t7\n"
    )
    print(f"  模拟源码树: {src}")

    r = run([sys.executable, str(ROOT / "scripts/prepare-source.py"), str(src)])
    print("\n".join("    " + l for l in r.stdout.strip().split("\n")))
    if r.returncode != 0:
        print("    [stderr] " + r.stderr.strip()[:400])
    chk(r.returncode == 0, "prepare-source.py 运行成功")

    for rel in ("filogic/base-files/etc/board.d/02_network",
                "filogic/base-files/lib/upgrade/platform.sh"):
        r = run(["sh", "-n", str(S / rel)])
        chk(r.returncode == 0, f"打补丁后 {Path(rel).name} 语法正确",
            r.stderr.strip()[:60])

    net = (S / "filogic/base-files/etc/board.d/02_network").read_text()
    chk('kst,wf3000a|\\' in net, "接口分组已并入（续行）")
    chk('ucidef_set_interfaces_lan_wan "lan1 lan2 lan3" wan' in net, "接口动作串正确")
    # MAC 必须是【从 factory 推导】，不能硬编码本机 MAC
    # 规则（方案甲）：基准 = factory 0x04(2.4G) - 2；LAN = 基准（= 机身标签）；WAN = 基准+1
    chk("mtd_get_mac_binary" in net, "MAC 从 factory 读取（非硬编码）")
    chk("wlan_2g_mac=$(mtd_get_mac_binary factory 4)" in net,
        "2.4G 读 factory:4 即 0x04")
    chk("wlan_5g_mac=$(mtd_get_mac_binary factory 10)" in net,
        "5G 读 factory:10 即 0x0a")
    chk('base_mac=$(macaddr_add "$wlan_2g_mac" -2)' in net, "基准 = 2.4G - 2")
    chk("lan_mac=$base_mac" in net, "LAN = 基准（= 机身标签地址）")
    chk("label_mac=$lan_mac" in net, "label = LAN")
    chk('wan_mac=$(macaddr_add "$base_mac" 1)' in net, "WAN = 基准 + 1")
    chk(not any(m in net for m in ("48:da:35:50:70:f5", "48:da:35:50:70:f6",
                                   "48:da:35:50:70:f7", "48:da:35:50:70:f8")),
        "未残留本机 MAC 硬编码")

    # mtwifi.sh：无线 MAC 从 factory 读取（动作 6）
    mtw = (src / ps.MTWIFI_SH_SRC).read_text()
    chk(ps.MTWIFI_MAC_MARK in mtw, "mtwifi.sh 已替换（含 MAC 读取函数）")
    chk("mtwifi_factory_mac 4" in mtw, "2.4G 读 factory 偏移 4 (0x04)")
    chk("mtwifi_factory_mac 10" in mtw, "5G 读 factory 偏移 10 (0x0a)")
    chk("lib/functions/system.sh" in mtw, "已 source system.sh")
    chk("mtd_get_mac_binary factory" in mtw, "确有 factory 读取调用")
    sh_mtw = run(["sh", "-n", str(src / ps.MTWIFI_SH_SRC)])
    chk(sh_mtw.returncode == 0, "mtwifi.sh shell 语法正确", sh_mtw.stderr.strip()[:60])

    # 上游改版时动作6 必须报错而非静默覆盖
    _bad = Path(tempfile.mkdtemp(prefix="wf3000a-mtw-"))
    (_bad / "package/mtk/applications/mtwifi-cfg/files").mkdir(parents=True)
    (_bad / ps.MTWIFI_SH_SRC).write_text(UPSTREAM_MTWIFI_SH.replace(
        "encryption=none", "encryption=psk2"))
    try:
        ps.patch_mtwifi_mac(_bad, ROOT / "custom/wf3000a", lambda a, b: None)
        chk(False, "上游改版时应报错停止")
    except RuntimeError as e:
        chk("缺少预期锚点" in str(e), "上游改版时明确报错（不静默覆盖）")

    plat = (S / "filogic/base-files/lib/upgrade/platform.sh").read_text()
    chk("kst,wf3000a)" in plat, "sysupgrade 分支已写入")

    lines = net.split("\n")
    idx = next(i for i, l in enumerate(lines) if l.strip() == "kst,wf3000a|\\")
    nxt = lines[idx + 1].strip()
    chk(nxt.endswith("|\\") or nxt.endswith(")"), "续行链完整未被打断", nxt[:40])


# ══════════════════════════════════════════════════════════════
# 4. 模拟 make defconfig + workflow 校验
# ══════════════════════════════════════════════════════════════
step("4. 模拟 make defconfig 与 workflow 校验")

# 真实存在的包（本源码是 MTK 闭源驱动方案，没有开源 mt76！）
AVAILABLE = {
    # LuCI 与基础
    "luci", "opkg", "ca-bundle", "ca-certificates", "luci-i18n-base-zh-cn",
    "libustream-openssl", "ppp", "ppp-mod-pppoe", "kmod-nft-offload",
    "luci-app-firewall", "luci-i18n-firewall-zh-cn",
    "luci-app-package-manager", "luci-i18n-package-manager-zh-cn",
    "uhttpd", "rpcd", "libuci", "libubus",
    # 硬件加速
    "kmod-mediatek_hnat",
    # ★ 无线：MTK 闭源驱动（源码 package/mtk/drivers 下真实存在）
    "kmod-mt_wifi", "kmod-warp", "kmod-conninfra", "wifi-dats", "mtwifi-cfg",
    "wifi-scripts", "datconf", "datconf-lua", "kvcedit", "libkvcutil",
    "mtk-smp", "wireless-regdb", "wireless-tools", "iw", "iwinfo",
    "luci-app-mtwifi-cfg", "luci-i18n-mtwifi-cfg-zh-cn",
}
# ⚠️ 注意：不含 kmod-mt7915e / kmod-mt7981-firmware / mt7981-wo-firmware
#    —— 这三个是上游 immortalwrt 的死引用，本源码里根本不存在。

DEVICE_SYMBOLS = {"kst_wf3000a", "qihoo_360t7"}

# ── ★ 无 prompt 符号：defconfig 会重置为 default ──────────────
# 键 = 符号名，值 = default（Kconfig 不保留 .config 里的赋值）
#
# ⚠️ 重要教训（v4 → v6）：
#   v4 曾试图把 MTK_RT_FIRST_IF_RF_OFFSET 改成 0x0，
#   做法是改 config.in 的 default。结果触发闭源驱动【编译失败】：
#     mt_wifi/embedded/common/eeprom.c: error: 'A32_RT2_OFFSET' undeclared
#   因为该内部符号只在官方默认（0xc0000）代码路径下定义。
#   ⇒ v6 起：编译期保持官方 0xc0000，实际偏移由运行期 l1profile.dat 覆盖。
NON_VISIBLE = {
    "CONFIG_MTK_RT_FIRST_IF_RF_OFFSET": ("0xc0000", "0xc0000"),
}

# 硬校验：缺失即中止编译
REQUIRED = [
    "CONFIG_TARGET_mediatek_filogic_DEVICE_kst_wf3000a",
    "CONFIG_PACKAGE_kmod-mediatek_hnat",
    "CONFIG_PACKAGE_luci",
    "CONFIG_LUCI_LANG_zh_Hans",
    # 无线（★ 没有这些 = 编出无 WiFi 的固件）
    "CONFIG_PACKAGE_kmod-mt_wifi",
    "CONFIG_PACKAGE_kmod-warp",
    "CONFIG_PACKAGE_kmod-conninfra",
    "CONFIG_PACKAGE_wifi-dats",
    "CONFIG_PACKAGE_mtwifi-cfg",
    "CONFIG_PACKAGE_wifi-scripts",
]

# 带值校验（对应 build.yml 的 required_kv）
REQUIRED_KV_PATCHED = {
    "CONFIG_MTK_CHIP_MT7981": "y",
    "CONFIG_MTK_WIFI_DRIVER": "y",
    "CONFIG_MTK_WIFI_FW_BIN_LOAD": "y",
    "CONFIG_MTK_MT7981_NEW_FW": "y",
}
# 注意：CONFIG_MTK_RT_FIRST_IF_RF_OFFSET 刻意【不在】校验列表。
#   它保持官方 0xc0000；改 0x0 会导致闭源驱动编译失败（A32_RT2_OFFSET）。
#   本机实际的 0x0 由运行期 l1profile.dat 覆盖。

RENAME_GROUPS = [
    ("LuCI 软件包页面", ["CONFIG_PACKAGE_luci-app-package-manager",
                          "CONFIG_PACKAGE_luci-app-opkg"]),
    ("软件包页面中文化", ["CONFIG_PACKAGE_luci-i18n-package-manager-zh-cn",
                          "CONFIG_PACKAGE_luci-i18n-opkg-zh-cn"]),
]
SOFT = ["CONFIG_PACKAGE_opkg", "CONFIG_PACKAGE_ca-bundle",
        "CONFIG_PACKAGE_ca-certificates"]


def defconfig(raw_symbols, available, devices, eeprom_patched=True):
    """模拟 make defconfig。

    四条规则（与真实 Kconfig 一致）：
      1) CONFIG_PACKAGE_x：包不存在 → 静默丢弃
      2) _DEVICE_x：机型不存在 → 静默丢弃
      3) ★ 无 prompt 符号 → 重置为 default，无视 .config 里的赋值
      4) 其余有 prompt 的符号 → 保留用户赋值

    输入 raw_symbols 是完整的 "KEY=VALUE" 列表（不能只给符号名，
    否则带值校验会因缺少 "=y" 而全部假失败）。
    """
    kept = []
    for s in raw_symbols:
        name = s.split("=")[0]
        if name in NON_VISIBLE:
            # 规则 3：不可见符号，值由 default 决定
            kept.append(f"{name}={NON_VISIBLE[name][0 if not eeprom_patched else 1]}")
            continue
        if name.startswith("CONFIG_PACKAGE_"):
            pkg = name[len("CONFIG_PACKAGE_"):]
            if pkg in available:
                kept.append(s)
        elif "_DEVICE_" in name:
            dev = name.split("_DEVICE_")[1]
            if dev in devices:
                kept.append(s)
        else:
            kept.append(s)
    return set(kept)


def has_sym(kept, sym):
    """kept 里是否含符号 sym（不论取值）。"""
    return any(k.split("=")[0] == sym for k in kept)


def value_of(kept, sym):
    """取符号 sym 的实际值，没有则返回 None。"""
    for k in kept:
        if k.split("=")[0] == sym:
            return k.split("=", 1)[1]
    return None


def validate(kept, label):
    print(f"\n  ── 场景：{label} ──")
    ok = True
    for sym in REQUIRED:
        if has_sym(kept, sym):
            print(f"    [OK  ] 硬校验 {sym}")
        else:
            print(f"    [FAIL] 硬校验 {sym}  ← 编译将中止")
            ok = False
    for k, v in REQUIRED_KV_PATCHED.items():
        cur = value_of(kept, k)
        if cur == v:
            print(f"    [OK  ] 带值校验 {k}={v}")
        else:
            print(f"    [FAIL] 带值校验 {k}={v}  实际 {k}={cur}  ← 编译将中止")
            ok = False
    for gname, group in RENAME_GROUPS:
        hit = next((s for s in group if has_sym(kept, s)), None)
        if hit:
            print(f"    [OK  ] 双名组 {gname} → {hit}")
        else:
            print(f"    [FAIL] 双名组 {gname}  ← 编译将中止")
            ok = False
    for sym in SOFT:
        if has_sym(kept, sym):
            print(f"    [OK  ] 软校验 {sym}")
        else:
            print(f"    [warn] 软校验 {sym}  ← 仅提醒，不中止")
    return ok


# 取完整的 "KEY=VALUE" 行（含 =m / =0x0 / ="mt_wifi" 等非 =y 项）
raw = [l.strip() for l in cfg_lines
       if l.startswith("CONFIG_") and not l.startswith("#") and "=" in l]
print(f"  config 中待解析符号 {len(raw)} 个")

# 场景 A：正常（已打 config.in 补丁）
kept = defconfig(raw, AVAILABLE, DEVICE_SYMBOLS, eeprom_patched=True)
chk(validate(kept, "A 正常（EEPROM 补丁已打）"), "场景A 全部通过")

# 场景 A2：EEPROM 偏移保持官方值（v6 起的行为，应通过校验）
kept_a2 = defconfig(raw, AVAILABLE, DEVICE_SYMBOLS, eeprom_patched=False)
ok_a2 = validate(kept_a2, "A2 EEPROM 偏移保持官方 0xc0000")
chk(ok_a2, "场景A2 通过（EEPROM 偏移不再进硬校验）")

# 场景 B：软项缺失
avail_b = AVAILABLE - {"ca-certificates"}
kept_b = defconfig(raw, avail_b, DEVICE_SYMBOLS)
chk(validate(kept_b, "B ca-certificates 缺失"), "场景B 软项缺失不误伤")

# 场景 C：device.mk 未追加
kept_c = defconfig(raw, AVAILABLE, {"qihoo_360t7"})
chk(not validate(kept_c, "C device.mk 未追加"), "场景C 正确拦截")

# 场景 D：中文丢失
raw_d = [s for s in raw if s.split("=")[0] != "CONFIG_LUCI_LANG_zh_Hans"]
kept_d = defconfig(raw_d, AVAILABLE, DEVICE_SYMBOLS)
chk(not validate(kept_d, "D 中文符号丢失"), "场景D 正确拦截")

# 场景 D2：i18n 兜底包缺失
avail_d2 = AVAILABLE - {"luci-i18n-base-zh-cn"}
kept_d2 = defconfig(raw, avail_d2, DEVICE_SYMBOLS)
chk(validate(kept_d2, "D2 兜底 i18n 包缺失"), "场景D2 兜底包缺失不误伤")

# 场景 E：源码只有旧名
avail_e = (AVAILABLE - {"luci-app-package-manager",
                        "luci-i18n-package-manager-zh-cn"}) | {
    "luci-app-opkg", "luci-i18n-opkg-zh-cn"}
kept_e = defconfig(raw, avail_e, DEVICE_SYMBOLS)
chk(validate(kept_e, "E 源码只有旧名 opkg"), "场景E 双名保险生效")

# 场景 E2：新旧名都没有
avail_e2 = AVAILABLE - {"luci-app-package-manager",
                        "luci-i18n-package-manager-zh-cn"}
kept_e2 = defconfig(raw, avail_e2, DEVICE_SYMBOLS)
chk(not validate(kept_e2, "E2 新旧名都缺失"), "场景E2 正确拦截")

# 场景 F：可选新增项缺失
avail_f = AVAILABLE - {"kmod-nft-offload", "ppp-mod-pppoe",
                       "libustream-openssl", "luci-app-firewall"}
kept_f = defconfig(raw, avail_f, DEVICE_SYMBOLS)
chk(validate(kept_f, "F 新增可选项缺失"), "场景F 新增项缺失不误伤")

# 场景 G：★ 无线包缺失（模拟又回到「没有 WiFi」的老问题）
avail_g = AVAILABLE - set(ps.WIRELESS_DEVICE_PKGS)
kept_g = defconfig(raw, avail_g, DEVICE_SYMBOLS)
chk(not validate(kept_g, "G 无线包缺失"), "场景G 正确拦截（防重演无 WiFi）")


# ══════════════════════════════════════════════════════════════
# 5. 幂等性
# ══════════════════════════════════════════════════════════════
if not SKIP_TREE:
    step("5. 幂等性检查（重复运行）")
    r = run([sys.executable, str(ROOT / "scripts/prepare-source.py"), str(src)])
    chk(r.returncode != 0 and "已存在" in r.stderr,
        "重复运行时明确报错停止", r.stderr.strip().split("\n")[-1][:70])
    shutil.rmtree(tmp, ignore_errors=True)


# ══════════════════════════════════════════════════════════════
# 6. 汇总
# ══════════════════════════════════════════════════════════════
shutil.rmtree(ROOT / "scripts/__pycache__", ignore_errors=True)

step("汇总")
print(f"  通过 {len(PASS)} 项")
if FAIL:
    print(f"  失败 {len(FAIL)} 项:")
    for f in FAIL:
        print(f"    - {f}")
    sys.exit(1)
print("  ✅ 全部通过")
