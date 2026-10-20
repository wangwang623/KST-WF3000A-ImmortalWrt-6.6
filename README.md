# WF3000A ImmortalWrt 6.6 云编译工程（纯净固件）

通过 GitHub Actions 云编译 **KST WF3000A**（MT7981B + 256MB RAM + 128MB Flash）的
ImmortalWrt 24.10 / Linux 6.6 固件。

**固件定位：纯净。** 官方默认包 + LuCI（中文）+ HNAT 硬件加速 + 无线驱动/固件，
**不含任何第三方插件**。需要什么插件刷完自己 `opkg install`。

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

对应十六进制：

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
| 源码（上游） | <https://github.com/padavanonly/immortalwrt-mt798x-6.6> | ImmortalWrt 24.10 + 内核 6.6，含 MTK 闭源无线驱动 |
| 源码（本工程使用） | <https://github.com/wangwang623/immortalwrt-mt798x-6.6> | 上游的 fork，**不做任何修改**，仅用于固定源码引用 |
| 参考工程 A | <https://github.com/Anser-y/WF3000A-ImmortalWrt-6.6> | WF3000A 移植的早期版本（大分区布局 + 大量插件） |
| 参考工程 B | 恩山无线论坛「小圆」的 WF3000A 固件 | 同为 padavanonly 6.6 源码，114M 布局，**有线/无线实测可用** |
| U-Boot | <https://github.com/VIKINGYFY/UBOOT-CI> | 多分区 U-Boot（含 114m 布局） |
| 项目文档 | <https://cmi.hanwckf.top/p/immortalwrt-mt798x/> | ImmortalWrt-MT798X 项目介绍（hanwckf） |

### 本工程与两个参考工程的差异

| | Anser-y | 小圆 | **本工程** |
|---|---|---|---|
| Flash 布局 | 大分区 | 114M（另有一个大分区变体） | **114M（单一）** |
| 插件 | 大量（PassWall / AdGuardHome / Tailscale 等） | 较多 | **无（纯净）** |
| MAC | 硬编码 | **随机**（DTS 缺 nvmem-cells） | **每台机器各自推导**（factory 偏移 + 增量） |
| 无线来源 | config 无无线配置 | 基于上游 defconfig | 同小圆：抄 `defconfig/mt7981-ax3000.config` |

> ⚠️ Anser-y 那份 `config/wf3000a.config` 里**没有任何无线配置**，
> 不能作为"无线正常"的参照物。

---

## 核心机制：源码仓库保持干净，补丁在 CI 里打

**`immortalwrt-mt798x-6.6` 源码一个字节都不手动改。**
所有移植改动由 `scripts/prepare-source.py` 在克隆之后、编译之前完成。

好处：源码可随意换版本，不用维护一整套 fork 差异。
代价：依赖锚点定位，上游改动文件格式时会失配——
所以脚本对致命项（DTS / 机型注册 / MAC）严格失败，对非致命项降级为警告。

### 目录

```
.github/workflows/build.yml     工作流（拉源码 → 打补丁 → 校验 → 编译）
config/wf3000a.config           固件配置（意图清单：只列要的）
custom/wf3000a/
  mt7981b-kst-wf3000a.dts       ①设备树：114MiB 分区 + 端口 + MAC nvmem
  device.mk                     ②镜像定义：机型注册 + IMAGE_SIZE + KERNEL
  02_network                    【参考】打完补丁后的完整文件
  platform.sh                   【参考】打完补丁后的完整文件
scripts/prepare-source.py       ★ 打补丁 + 复核（核心）
scripts/simulate.py             本地模拟运行（不用等 CI）
开ssh和救砖/                     解锁 SSH 与串口救砖资料
```

`custom/wf3000a/` 下的 `02_network` 和 `platform.sh` **只用于查看补丁效果**，
脚本不会复制它们——它会自己在源码文件上做插入。

### 脚本做的四件事

| # | 动作 | 目标文件 | 为什么 |
|---|---|---|---|
| 1 | 复制 DTS | `mediatek/dts/mt7981b-kst-wf3000a.dts` | 分区 / 端口 / GPIO / MAC 全靠它 |
| 2 | 追加镜像定义 | `mediatek/image/filogic.mk` | **让 config 符号存在** |
| 3 | 改网络配置 | `filogic/base-files/etc/board.d/02_network` | 端口划分 + MAC |
| 4 | 改升级脚本 | `filogic/base-files/lib/upgrade/platform.sh` | 打通 sysupgrade |

打完补丁后逐条复核，缺哪项报哪项——**不会编出一台"别的机型"的固件**。

---

## 无线：MTK 闭源驱动（这份源码没有 mt76）

已递归核对上游全部 12803 个文件确认：

- `package/kernel/mt76` **目录不存在**
- 全树**没有任何** Makefile 定义 `mt7981-firmware` / `mt7981-wo-firmware`

所以 `filogic.mk` 里其他机型写的 `kmod-mt7915e` / `kmod-mt7981-firmware` /
`mt7981-wo-firmware` 全是**死引用**，会被 `make defconfig` 静默丢弃——
**这正是最初"固件没有无线"的根因**。

本源码真正可用的无线是 **MTK 闭源驱动**，包都在仓库里：

| 包 | 路径 | 作用 |
|---|---|---|
| `kmod-mt_wifi` | `package/mtk/drivers/mt_wifi` | mt_wifi.ko 闭源驱动 |
| `kmod-warp` | `package/mtk/drivers/warp` | WED 硬件卸载 |
| `kmod-conninfra` | `package/mtk/drivers/conninfra` | 连接基础设施 |
| `wifi-dats` | `package/mtk/drivers/wifi-profile` | mt7981 profile(.dat) |
| `mtwifi-cfg` | `package/mtk/applications/mtwifi-cfg` | 无线配置工具 |

**无线不会自动带出来**——`filogic/target.mk` 的 `DEFAULT_PACKAGES` 里没有它，
`filogic.mk` 的 134 处 `DEVICE_PACKAGES` 里也没有一处写 `kmod-mt_wifi`。
必须在 `config/wf3000a.config` 里显式写 `=y`。

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

硬编码 `48:da:35:50:70:f5` 会把**本机**的 MAC 写进固件。
别人刷了这份固件，就会与本机构成 **MAC 冲突**（同网段两台设备同 MAC）。

从每台机器自己的 factory 读取 → 每台机器得到自己的 MAC，**固件可公开分发**。

### 实现方式

`02_network` 里的 `kst,wf3000a` 分支：

```sh
kst,wf3000a)
	# 以 2.4G 无线 MAC 为基准推导，每台机器各不相同
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
> 0x5070f7 + (-1) & 0xffffff = 0x5070f6   → LAN ...:70:f6
> 0x5070f7 + (-2) & 0xffffff = 0x5070f5   → WAN ...:70:f5
> ```
> 已用源码原始实现实测验证，跨字节借位也正确。

### 无线 MAC

2.4G / 5G 的 MAC 由**闭源驱动直接从 EEPROM 读**（`0x04` / `0x0a`），
不经过 `02_network`，无需处理。

### DTS 部分

`gmac0` / `gmac1` 挂 `nvmem-cells = <&macaddr_factory_4>`（同样从 factory `0x04` 读）。

> 这就是"MAC 随机"问题的解法——小圆那版 DTS 里没有 nvmem-cells，所以 MAC 是随机的。

---

## 使用步骤

1. 本目录内容作为**独立仓库**上传到 GitHub
2. **Settings → Actions → General → Workflow permissions** 勾 **Read and write**
3. Actions → `Build WF3000A ImmortalWrt 6.6` → **Run workflow**
   - `source_ref`：源码分支名或 commit SHA（默认 `openwrt-24.10-6.6`）
   - `publish_release`：是否发布 GitHub Release
4. 等 1~2 小时，产物在 **Artifacts**

产物文件名带 `kst_wf3000a` 即说明选对了机型：

```
immortalwrt-...-mediatek-filogic-kst_wf3000a-initramfs-kernel.bin
immortalwrt-...-mediatek-filogic-kst_wf3000a-squashfs-factory.bin
immortalwrt-...-mediatek-filogic-kst_wf3000a-squashfs-sysupgrade.bin
```

### 关于源码版本

`source_ref` 默认填**分支名**，会跟着源码仓库变动，以便跟进上游更新。

若需要**复现某次成功构建**：打开那次运行的 Release，body 里记录了
实际使用的 `Commit`（短 SHA）与 `Kernel` 版本，把它填进 `source_ref` 即可锁死。

源码同步上游后若 `defconfig/mt7981-ax3000.config` 有变更，
workflow 第 7 步（`Cross-check MTK symbols`）会在几分钟内报错并列出差异——
它兼作**上游变更警报器**。

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
# 下面两个应相差 1，且都比 2.4G 无线 MAC 小（LAN 小 1、WAN 小 2）
cat /sys/class/net/lan1/address   # 本机示例 48:da:35:50:70:f6
cat /sys/class/net/wan/address    # 本机示例 48:da:35:50:70:f5

# 基准（2.4G）可从 factory 直接读出来对照
hexdump -C -n 16 /dev/mtd2        # factory：0x04 = ...F7，0x0a = ...F8
dmesg | grep -iE "mt_wifi|warp|conninfra|eeprom"
```

---

## 本地模拟运行（推荐先跑一遍）

不用等 CI、不用真编译，几十秒验证整条链路：

```bash
python3 scripts/simulate.py
```

它会：

1. 校验 `prepare-source.py` / `build.yml` / 两个 shell 参考文件的语法
2. 建一棵模拟源码树，跑一遍打补丁，检查补丁位置与续行链
3. 模拟 `make defconfig` 的符号解析，跑硬校验 / 软校验
4. 跑多个场景（全部可用 / 软项缺失 / 机型符号丢失 / 无线包缺失 …）
5. 检查幂等性（重复运行是否报错停止）

也可以直接对真实源码跑打补丁脚本：

```bash
git clone --depth=1 -b openwrt-24.10-6.6 \
  https://github.com/wangwang623/immortalwrt-mt798x-6.6
python3 scripts/prepare-source.py ./immortalwrt-mt798x-6.6
```

⚠️ 脚本**不能重复运行**——第二次会因 `filogic.mk` 里已有 `kst_wf3000a`
直接报明确错误停下（而不是生成错误固件）。CI 每次都是全新克隆，不会遇到。

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

`config/wf3000a.config` 里的 **MTK 驱动符号块**是**逐行照抄**
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
workflow 第 7 步会做这个双向比对，有差异直接拦下。

---

## 编进固件 vs 事后安装

判断标准（这条决定了 config 里该写什么）：

| 类型 | 编进去？ | 理由 |
|---|---|---|
| `kmod-*` | **必须** | 与内核版本强绑定，事后 `opkg install` 必然失败 |
| `ca-bundle` / `ca-certificates` | **必须** | 否则 opkg 连不上 https 源，「按需安装」本身不成立 |
| `CONFIG_LUCI_LANG_zh_Hans` | **必须** | 不是插件，是 LuCI 的语言配置项，必须编译期确定 |
| 无线驱动 / 固件 | **必须** | 否则没有 WiFi（见上文） |
| `luci` | 建议 | 让机器可用的基础 |
| `luci-app-*` | 不必 | 纯脚本/二进制，随时 `opkg install` |
| 界面语言、主题 | 不必 | 同上 |

所以当前 config 只编这几类：**机型 + HNAT(kmod) + 无线驱动/固件 + LuCI(含 https 依赖)**。

想确认最终编了什么：看 workflow 输出的 `build.diffconfig`，
或刷完后在路由器上跑 `opkg list-installed`。

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

### 两个常见疑问

**`luci-app-package-manager`**（LuCI 里的「软件包」页面）：
不是基础系统包，是 luci-app 类插件。缺了 LuCI 里没有该菜单，
**不影响**从 SSH 用 `opkg install`。随时能补。

**`luci-ssl`**（让 LuCI 走 HTTPS）：
元包，拉进 `uhttpd-mod-tls` + SSL 后端 + `px5g`（自签证书）。
缺了 LuCI 只能 `http://` 访问，家内局域网无所谓。随时能补。

⚠️ 别把它和 `ca-bundle` 搞混：

```
luci-ssl     →  入站 HTTPS：浏览器 ──▶ 路由器管理页
ca-bundle    →  出站 HTTPS：路由器 ──▶ 软件源下载插件
```

方向相反、用途不同。本工程**保留**了出站用的 ca-bundle / ca-certificates，
**省略**了入站用的 luci-ssl。
