#!/bin/sh
#
# Copyright (C) 2023, hanwckf <hanwckf@vip.qq.com>
#

# ── WF3000A 修改：无线 MAC 从 factory 分区读取 ──────────────────
# 原版 detect 不设 macaddr，驱动会从 EEPROM 自行派生，
# 结果 2.4G/5G 都不是 factory 里记录的值（且 5G 被强制加 LAA 位 0x02）。
#
# 这里在【生成 /etc/config/wireless 时】就按 factory 偏移写入：
#   2.4G(idx=1) ← factory 偏移 0x04  (本机 = ...:F7)
#   5G          ← factory 偏移 0x0a  (本机 = ...:F8)
# 每台机器读自己的 flash，固件可公开分发，不会与他人撞 MAC。
#
# 注意：闭源驱动仍会忽略 5G 的 macaddr（实测 BSSID 恒为 LAA(2.4G)），
#       这是驱动固有行为，改配置解决不了。此处写入仅为配置自洽。
# ──────────────────────────────────────────────────────────────

[ -f /lib/functions.sh ] && . /lib/functions.sh
[ -f /lib/functions/system.sh ] && . /lib/functions/system.sh

append DRIVERS "mtwifi"

# 从 factory 指定偏移读 MAC；读不到就返回空（让驱动用默认值）
mtwifi_factory_mac() {
	local off="$1" m=""
	command -v mtd_get_mac_binary >/dev/null 2>&1 || return 1
	m="$(mtd_get_mac_binary factory "$off" 2>/dev/null)"
	case "$m" in
		""|"00:00:00:00:00:00"|"ff:ff:ff:ff:ff:ff"|"FF:FF:FF:FF:FF:FF") return 1 ;;
	esac
	echo "$m"
}

detect_mtwifi() {
	local idx ifname
	local band hwmode htmode htbsscoex ssid dbdc_main channel macaddr macaddr_line
	if [ -d "/sys/module/mt_wifi" ]; then
		dev_list="$(l1util list)"
		for dev in $dev_list; do
			config_get type ${dev} type
			[ "$type" = "mtwifi" ] || {
				ifname="$(l1util get ${dev} main_ifname)"
				idx="$(l1util get ${dev} subidx)"
				if [ $idx -eq 1 ]; then
					band="2g"
					hwmode="11g"
					htmode="HE40"
					htbsscoex="1"
					ssid="ImmortalWrt-2.4G"
					dbdc_main="1"
					txpower="100"
					channel="auto"
					# factory 偏移 0x04 = 2.4G 无线 MAC（本机 ...:F7）
					macaddr="$(mtwifi_factory_mac 4)"
				else
					band="5g"
					hwmode="11a"
					htmode="HE160"
					htbsscoex="0"
					ssid="ImmortalWrt-5G"
					channel="36"
					txpower="100"
					dbdc_main="0"
					# factory 偏移 0x0a = 5G 无线 MAC（本机 ...:F8）
					macaddr="$(mtwifi_factory_mac 10)"
				fi
				# 读不到时不写这一项，避免留下空值
				if [ -n "$macaddr" ]; then
					macaddr_line="set wireless.default_${dev}.macaddr=${macaddr}"
				else
					macaddr_line=""
				fi
				uci -q batch <<-EOF
					set wireless.${dev}=wifi-device
					set wireless.${dev}.type=mtwifi
					set wireless.${dev}.phy=${ifname}
					set wireless.${dev}.hwmode=${hwmode}
					set wireless.${dev}.band=${band}
					set wireless.${dev}.dbdc_main=${dbdc_main}
					set wireless.${dev}.channel=${channel}
					set wireless.${dev}.txpower=${txpower}
					set wireless.${dev}.htmode=${htmode}
					set wireless.${dev}.country=CN
					set wireless.${dev}.mu_beamformer=1
					set wireless.${dev}.noscan=${htbsscoex}
					set wireless.${dev}.wapp=0
					set wireless.${dev}.serialize=1
					
					set wireless.default_${dev}=wifi-iface
					set wireless.default_${dev}.device=${dev}
					set wireless.default_${dev}.network=lan
					set wireless.default_${dev}.mode=ap
					set wireless.default_${dev}.ssid=${ssid}
					set wireless.default_${dev}.encryption=none
					${macaddr_line}
EOF
				uci -q commit wireless
			}
		done
	fi
}

