# KST-WF3000A ImmortalWrt 6.6 云编译工程（纯净固件）

通过 GitHub Actions 云编译 **KST WF3000A**（MT7981B + 256MB RAM + 128MB Flash）的
ImmortalWrt 24.10 / Linux 6.6 固件。

**固件定位：纯净。** 官方默认包 + LuCI（中文）+ HNAT 硬件加速 + 无线驱动/固件，
**不含任何第三方插件**。需要什么插件刷完自己 `opkg install`。

---

## 方案：源码用上游官方源，移植改动在 CI 里打

| | 内容 |
|---|---|
| **源码** | <https://github.com/padavanonly/immortalwrt-mt798x-6.6>（**上游官方，原样不动**） |
| **本仓库** | DTS / device.mk / 补丁脚本 / config / workflow |

### 为什么这样选

**好处：源码零维护。** 不需要维护 fork，没有同步、没有冲突。
换版本只改 workflow 的 `source_ref` 输入框（分支名或 commit SHA）即可。

**代价：依赖查找替换。** DTS 复制、`filogic.mk` 追加、`02_network` 与
`platform.sh` 的插入全靠正则 / 锚点定位，上游改文件格式时可能失配。

为降低这个代价，脚本做了分级处理：

- 致命项（DTS / 机型注册 / MAC）**严格失败**
- 非致命项（sysupgrade）**降级为警告**，避免误判成编译错误
- 打完补丁后逐条复核，缺哪项报哪项

---

## 硬件与布局

| 项目 | 值 |
|---|---|
| SoC | MediaTek MT7981B（双核 A53 @ 1.3GHz） |
| 内存 | 256 MB |
| Flash | **128 MB**（SPI-NAND，带 NMBM） |
| 无线 | MT7976，2.4G + 5G 双频 AX3000 |
| 分区布局 | **114M（expand）** |

### MTD 布局列表（U-Boot 里二选一）

```text
default:      nmbm0:1024k(bl2),512k(u-boot-env),2048k(factory),2048k(fip),49152k(ubi),49152k(ubi1)
expand(114m): nmbm0:1024k(bl2),512k(u-boot-env),2048k(factory),2048k(fip),116736k(ubi)
```

**本工程只编译 `expand(114m)` 这一种。** 刷机时 U-Boot 布局也必须选 **114m**，两者必须对应。

| 分区 | 起始 | 大小 |
|---|---:|---:|
| bl2 | `0x0000000` | `0x0100000` |
| u-boot-env | `0x0100000` | `0x0080000` |
| factory | `0x0180000` | `0x0200000` |
| fip | `0x0380000` | `0x0200000` |
| ubi | `0x0580000` | `0x07200000`（116736 KiB） |

DTS 里 `ubi` 为 `0x07200000`，`device.mk` 里 `IMAGE_SIZE` 为 `115712k`——
比 ubi 少 1 MiB，留给 NMBM 坏块表与 UBI 开销。

---

## 刷机前提：先解锁 SSH 并刷入多分区 U-Boot

固件是 114M 大分区版本，**必须先刷入多分区 U-Boot** 才能使用。

1. **解锁 SSH**：在路由器配置项中导入 `开ssh和救砖/nl_wr8103-sysbackup-ssh.bin`，
   然后**拔电源重启**，即可开启 SSH。
2. **刷入 U-Boot**：推荐用 PuTTY + WinSCP 操作。

U-Boot 下载地址：
<https://github.com/VIKINGYFY/UBOOT-CI>
（`release/Yuzhii0718-SP2-26.10.12`，文件名
`fip-mt7981_kst_wf3000a_SP2-Yuzhii-dhcpd-fixed-parts-multi-layout_md5-63d9666dae57cd3db2da4e20c20fec22-26.10.12.bin`）

该 U-Boot 源码基于 <https://github.com/Yuzhii0718/bl-mt798x-dhcpd>。

> 串口救砖方法见 `开ssh和救砖/MediaTek Filogic 系列路由器串口救砖教程.md`。

---

## 参考地址

| 项目 | 地址 | 说明 |
|---|---|---|
| 源码（本工程使用） | <https://github.com/padavanonly/immortalwrt-mt798x-6.6> | **直接用上游官方源**，ImmortalWrt 24.10 + 内核 6.6，含 MTK 闭源无线驱动 |
| 参考工程 A | <https://github.com/Anser-y/WF3000A-ImmortalWrt-6.6> | WF3000A 移植的早期版本（大分区布局 + 大量插件） |
| 参考工程 B | 恩山无线论坛「小圆」的 WF3000A 固件 | 同为 padavanonly 6.6 源码，114M 布局，**有线/无线实测可用** |
| U-Boot | <https://github.com/VIKINGYFY/UBOOT-CI> | 多分区 U-Boot（含 114m 布局） |
| 项目文档 | <https://cmi.hanwckf.top/p/immortalwrt-mt798x/> | ImmortalWrt-MT798X 项目介绍（hanwckf） |

### 与两个参考工程的差异

| | Anser-y | 小圆 | **本工程** |
|---|---|---|---|
| Flash 布局 | 大分区 | 114M（另有一个大分区变体） | **114M（单一）** |
| 插件 | 大量（PassWall / AdGuardHome / Tailscale 等） | 较多 | **无（纯净）** |
| MAC | 硬编码 | **随机**（DTS 缺 nvmem-cells） | **每台机器各自推导** |
| 无线来源 | config 无无线配置 | 基于上游 defconfig | 同小圆：抄 `defconfig/mt7981-ax3000.config` |

> ⚠️ Anser-y 那份 `config/wf3000a.config` 里**没有任何无线配置**，
> 不能作为"无线正常"的参照物。

---

## 无线：MTK 闭源驱动（这份源码没有 mt76）

已递归核对上游全部 12803 个文件确认：

- `package/kernel/mt76` **目录不存在**
- 全树**没有任何** Makefile 定义 `mt7981-firmware` / `mt7981-wo-firmware`

所以 `filogic.mk` 里其他机型写的 `kmod-mt7915e` / `kmod-mt7981-firmware` /
`mt7981-wo-firmware` 全是**死引用**，会被 `make defconfig` 静默丢弃——
**这正是最初"固件没有无线"的根因**。

本源码真正可用的无线是 **MTK 闭源驱动**：

| 包 | 路径 | 作用 |
|---|---|---|
| `kmod-mt_wifi` | `package/mtk/drivers/mt_wifi` | mt_wifi.ko 闭源驱动 |
| `kmod-warp` | `package/mtk/drivers/warp` | WED 硬件卸载 |
| `kmod-conninfra` | `package/mtk/drivers/conninfra` | 连接基础设施 |
| `wifi-dats` | `package/mtk/drivers/wifi-profile` | mt7981 profile(.dat) |
| `mtwifi-cfg` | `package/mtk/applications/mtwifi-cfg` | 无线配置工具 |

**无线不会自动带出来**——`filogic/target.mk` 的 `DEFAULT_PACKAGES` 里没有它，
`filogic.mk` 的 134 处 `DEVICE_PACKAGES` 里也没有一处写 `kmod-mt_wifi`。
必须在 `defconfig/wf3000a.config` 里显式写 `=y`。

### 闭源驱动的固有行为（不是 bug）

- LuCI 里 `iwinfo` 不可用，无线状态看 `luci-app-mtwifi-cfg` 或用 `iwpriv ra0`
- 不能改 `/etc/config/wireless`，要改 `/etc/wireless/mt7981/` 下的 `.dat` profile
- 中继扫描时同频段设备会短暂断开
- IGMP Snooping 可能有问题（新版源码已默认关闭）

---

## MAC：从 factory 推导，不硬编码

### 分配规律（本机实测）

| 来源 | 值 | 说明 |
|---|---|---|
| factory `0x04` | `48:DA:35:50:70:F7` | **2.4G 无线** ← 基准 MAC |
| factory `0x0a` | `48:DA:35:50:70:F8` | **5G 无线** |
| 推导 `base-1` | `48:DA:35:50:70:F6` | **LAN** |
| 推导 `base-2` | `48:DA:35:50:70:F5` | **WAN**（与机身标签一致） |

即：

```
base = factory 分区偏移 0x04 处的 MAC   ← 2.4G 无线
LAN  = base - 1
WAN  = base - 2
```

> ⚠️ **注意工厂里没有 F5**：`48:DA:35:50:70:F5` 只出现在机身标签上，
> factory 分区里**不存在**，只有 `0x04=F7` 和 `0x0a=F8` 两个无线 MAC。
> 所以必须从 `0x04` 读基准再往下推算，不能直接读 F5。

### 为什么不硬编码

硬编码会把本机 MAC 写死进固件，别人刷了就跟你**撞 MAC**（同网段两台设备同 MAC）。
从每台机器自己的 factory 读取 → 每台机器得到自己的 MAC，**固件可公开分发**。

### 实现方式

由 `scripts/prepare-source.py` 插入 `02_network` 的分支：

```sh
kst,wf3000a)
	base_mac=$(mtd_get_mac_binary factory 4)
	lan_mac=$(macaddr_add "$base_mac" -1)
	wan_mac=$(macaddr_add "$base_mac" -2)
	label_mac=$lan_mac
	;;
```

> **为什么用 `macaddr_add` 传负数而不是 `macaddr_sub`**
> 这份源码的 `/lib/functions/system.sh` 只有 `macaddr_add`，**没有** `macaddr_sub`。
> `macaddr_add` 内部是 `(0x<nic> + val) & 0xffffff`，传负数靠补码回绕，等价减法：
> ```
> 0x5070f7 + (-1) & 0xffffff = 0x5070f6   → LAN
> 0x5070f7 + (-2) & 0xffffff = 0x5070f5   → WAN
> ```
> 源码自带的 02_network 里就有 `macaddr_add "$lan_mac" -2` 的用法，实测可行。

### 无线 MAC：由动作 6 改 `mtwifi.sh`

有线 MAC 由 `02_network` 处理，无线则不同——它由
`package/mtk/applications/mtwifi-cfg/files/mtwifi.sh` 的 `detect_mtwifi()`
在生成 `/etc/config/wireless` 时决定。

**原版问题**：`detect_mtwifi()` 根本不设 `macaddr`，驱动于是从 EEPROM
自行派生。实机实测结果：

```
2.4G = ...:F9                    ← factory 里记录的是 F7
5G   = 4A:DA:35:50:70:F9         ← 首字节被置 LAA 位（0x48 | 0x02）
```

**改法**（动作 6）：在生成配置时按 factory 偏移写入

```sh
if [ $idx -eq 1 ]; then          # 2.4G
    macaddr="$(mtwifi_factory_mac 4)"      # factory 0x04 → F7
else                             # 5G
    macaddr="$(mtwifi_factory_mac 10)"     # factory 0x0a → F8
fi
```

配套一个带容错的读取函数（读不到就不写，避免留空值）：

```sh
mtwifi_factory_mac() {
	local off="$1" m=""
	command -v mtd_get_mac_binary >/dev/null 2>&1 || return 1
	m="$(mtd_get_mac_binary factory "$off" 2>/dev/null)"
	case "$m" in
		""|"00:00:00:00:00:00"|"ff:ff:ff:ff:ff:ff"|"FF:FF:FF:FF:FF:FF") return 1 ;;
	esac
	echo "$m"
}
```

**为什么用整文件替换而不是查找插入**：本工程其它动作都靠正则/锚点做插入，
上游改格式就失配——这正是查找替换最脆弱的地方。`mtwifi.sh` 只有 65 行、
改动点 5 处，整文件替换反而更可靠。为防上游大改时被静默覆盖，
替换前先校验 5 个锚点，任一缺失即**报错停止**（不静默覆盖）。

> ⚠️ **闭源驱动仍会忽略 5G 的 macaddr**
> 实测：LuCI 里设 `48:...:F8` 或 `4A:...:F9`，`b1.dat` 里也确实写成了 F8，
> 但 BSSID 恒为 `LAA(2.4G)`。这是驱动固有行为，改配置解决不了。
> 本动作的**实际收益是让 2.4G 默认即为 F7**（刷完不用手动设一次）。

**生效时机**：只在生成 `/etc/config/wireless` 时执行
（全新刷机，或删掉该文件后重启）。sysupgrade 保留配置时沿用旧配置。

---

## 使用步骤

1. 本目录内容作为**独立仓库**上传到 GitHub
2. **Settings → Actions → General → Workflow permissions** 勾 **Read and write**
3. Actions → `Build KST-WF3000A ImmortalWrt 6.6` → **Run workflow**
   - `source_ref`：上游源码的分支名或 commit SHA（默认 `openwrt-24.10-6.6`）
   - `publish_release`：是否发布 GitHub Release
4. 等 1~2 小时，产物在 **Artifacts**

产物文件名带 `kst_wf3000a` 即说明选对了机型：

```
immortalwrt-...-mediatek-filogic-kst_wf3000a-initramfs-kernel.bin
immortalwrt-...-mediatek-filogic-kst_wf3000a-squashfs-factory.bin
immortalwrt-...-mediatek-filogic-kst_wf3000a-squashfs-sysupgrade.bin
```

### 关于源码版本

`source_ref` 填**分支名**会跟着上游变动，可跟进安全更新和内核升级。

若需要**复现某次成功构建**：打开那次运行的 Release，body 里记录了实际使用的
`Commit`（短 SHA）与 `Kernel` 版本，把它填进 `source_ref` 即可锁死版本。

因为源码是上游官方源，**不存在同步冲突问题**——但反过来，上游改版可能让
补丁脚本失配，这时第 5 步会明确报错指出是哪一处没匹配上。

---

## 目录结构

```
.github/workflows/build.yml     云编译流程
defconfig/wf3000a.config        构建配置（意图清单）
custom/wf3000a/
  mt7981b-kst-wf3000a.dts       ①设备树（新增）
  device.mk                     ②机型定义（追加到 filogic.mk）
  02_network                    ③参考：打完补丁后的样子
  platform.sh                   ④参考：打完补丁后的样子
  mtwifi.sh                     ⑤改好的完整版（整文件替换，见下）
scripts/
  prepare-source.py             打补丁 + 事后复核
  simulate.py                   本地模拟（不需要真的编译）
```

> **别和源码的 `defconfig/` 搞混**：这里的 `defconfig/` 属于【本构建仓库】，
> 放的是本工程自己的配置。源码仓库里也有一个 `defconfig/`（放
> `mt7981-ax3000.config` 等官方基线），那是上游的东西，两者无关。
> 本工程的配置文件沿用 `defconfig/` 这个目录名，是为了和源码的用法保持一致。

`custom/wf3000a/` 里的 `02_network` 和 `platform.sh` 是**参考文件**——
云编译不读它们（`prepare-source.py` 直接在源码文件上做插入），
只有 `simulate.py` 会读，用来反推"未打补丁"的版本做对照测试。

---

## 本地模拟（可选）

不用 GitHub Actions、不用真的编译，就能验证补丁逻辑：

```bash
python3 scripts/simulate.py
```

会检查：脚本语法、YAML、config 格式、补丁后的 shell 语法、
补丁位置正确性、幂等性，以及多个「异常场景」能否被正确拦住。

---

## 刷机

### 首次（强烈建议先走内存启动）

1. U-Boot Web（<http://192.168.1.1>），布局选 **114m**
2. 先上传 **`initramfs-kernel.bin`** —— 内存启动，**不写 flash**，零风险
3. SSH 进去确认无线正常后再刷正式包

```sh
dmesg | grep -iE "FLASH OFFSET|NVM is FLASH|eeprom"
# 看到 FLASH OFFSET [0x0] → 读到了原厂校准数据
```

4. 确认无误后，U-Boot Web 上传 **`factory.bin`**

### 后续升级

```sh
sysupgrade -n /tmp/xxx-sysupgrade.bin
```

⚠️ 三个文件不能混用：

| 文件 | 用途 |
|---|---|
| `initramfs-kernel.bin` | 内存启动验证（不写 flash） |
| `factory.bin` | U-Boot Web 首次刷入 |
| `sysupgrade.bin` | 系统内升级 |

### 验证

```sh
cat /sys/class/net/lan1/address   # 本机示例 48:da:35:50:70:f6
cat /sys/class/net/wan/address    # 本机示例 48:da:35:50:70:f5
hexdump -C -n 16 /dev/mtd2        # 基准：0x04 = ...F7
dmesg | grep -iE "mt_wifi|warp|conninfra|eeprom"
```

---

## workflow 的四道校验

都不改变编译行为，只在有问题时**提前失败**——避免「编译两小时、刷机才发现没 WiFi」。

| 步骤 | 时机 | 检查 |
|---|---|---|
| 第 5 步 | 编译前 | 打补丁（5 个动作）+ 事后复核（DTS / 机型 / MAC / sysupgrade / mtwifi.sh / 无线包） |
| 第 6 步 | defconfig 前 | 5 个无线包 + MT7981 固件 + l1profile.dat |
| 第 8 步 | defconfig 前 | config 的 MTK 驱动符号与上游 defconfig **双向**比对 |
| 第 9 步 | defconfig 后 | 无线包是否被静默丢弃 |
| 第 12 步 | 编译后 | manifest 含无线包 + rootfs 含固件 bin |

失败时第 11 步会自动打印磁盘、目录体积、最后 120 行日志和 grep 出的错误行。

---

## config 是「意图清单」，不是「全量快照」

只写要的，不写不要的：

```sh
CONFIG_PACKAGE_luci=y        # 要
# 不写的包，默认就是不编译
```

**依赖不需要手写**：`make defconfig` 会沿依赖树自动展开。
只写 `luci`，就会自动补上 uhttpd / rpcd / libuci / libubus / ...

### ⚠️ 唯一的例外：无线驱动符号必须连 `is not set` 一起抄

`defconfig/wf3000a.config` 里的 **MTK 驱动符号块**是**逐行照抄**
源码自带的 `defconfig/mt7981-ax3000.config`，**包括 `# CONFIG_X is not set` 行**。

原因：这批符号在 `mt_wifi/config.in` 里是 `default y`，
不显式写 `# CONFIG_X is not set` 就会被默认打开。曾因漏抄两条导致编译失败：

```
eeprom.c:508  error: 'PRE_CAL_SIZE_ONE_CARD' undeclared
eeprom.c:539  error: 'PRECALPART_OFFSET'     undeclared
...
ERROR: package/mtk/drivers/mt_wifi failed to build.
```

**只比对"我写了什么"不够，还要比对"上游禁用了什么"。**
workflow 第 8 步会做这个双向比对，有差异直接拦下。

---

## 编进固件 vs 事后安装

| 类型 | 编进去？ | 理由 |
|---|---|---|
| `kmod-*` | **必须** | 与内核版本强绑定，事后 `opkg install` 必然失败 |
| `ca-bundle` / `ca-certificates` | **必须** | 否则 opkg 连不上 https 源 |
| `CONFIG_LUCI_LANG_zh_Hans` | **必须** | 不是插件，是 LuCI 的语言配置项 |
| 无线驱动 / 固件 | **必须** | 否则没有 WiFi |
| `luci` | 建议 | 让机器可用的基础 |
| `luci-app-*` | 不必 | 纯脚本/二进制，随时 `opkg install` |
| 界面语言、主题 | 不必 | 同上 |

想确认最终编了什么：看 workflow 输出的 `build.diffconfig`，
或刷完后跑 `opkg list-installed`。

---

## 以后装插件

```sh
opkg update && opkg install luci-app-xxx
```

常用：

```sh
opkg install luci-app-upnp luci-app-ddns luci-app-wol   # 网络小工具
opkg install luci-app-package-manager                    # LuCI「软件包」页面
opkg install luci-ssl                                    # LuCI 走 HTTPS
opkg install zram-swap                                   # 内存压缩
```

⚠️ 带 `kmod-*` 的包（如 `kmod-wireguard`）必须重新编译后刷入，
事后装会因内核版本不匹配失败。

> **`luci-ssl` 与 `ca-bundle` 别搞混**：
> `luci-ssl` 是入站 HTTPS（浏览器 → 管理页），`ca-bundle` 是出站 HTTPS（路由器 → 软件源）。
> 方向相反。本工程**保留**了 ca-bundle，**省略**了 luci-ssl（家内 http 够用）。

---

## 附：源码本地编译步骤（参考上游官方 README）

本项目走 GitHub Actions 云编译，不需要本地编译。若想在本机编译，
参考上游 <https://github.com/padavanonly/immortalwrt-mt798x-6.6> 的 Quickstart：

1. 克隆源码
   ```bash
   git clone -b openwrt-24.10-6.6 --single-branch --filter=blob:none \
     https://github.com/padavanonly/immortalwrt-mt798x-6.6
   cd immortalwrt-mt798x-6.6
   ```
2. 更新并安装 feeds
   ```bash
   ./scripts/feeds update -a
   ./scripts/feeds install -a
   ```
3. 载入配置
   ```bash
   cp -f defconfig/mt7981-ax3000.config .config
   ```
4. 编译
   ```bash
   make -j$(nproc)
   ```

注意（来自官方 README）：

- 用**非 root 用户**操作，不要 sudo
- PATH 和工作目录**不能有空格或非 ASCII 字符**
- 至少 4GB 内存、25GB 磁盘，且能联网
- Debian 11 优先，需 AMD64 架构

若在 WSL 下编译，需移除 PATH 中的 Windows 目录。
