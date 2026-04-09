#!/bin/bash
INSTALL_MODE="auto"
DINGTALK_VER="latest"
TEMP_DIR="/tmp/dingtalk_install"
LOG_FILE="/var/log/dingtalk_install.log"
LOCAL_DEB=""  # 新增：本地DEB文件路径变量

RED='\033[31m'
GREEN='\033[32m'
YELLOW='\033[33m'
BLUE='\033[34m'
RESET='\033[0m'

init() {
    [ "$(id -u)" -ne 0 ] && {
        echo -e "${RED}请使用 sudo 或以 root 用户运行此脚本！${RESET}"
        exit 1
    }
    mkdir -p "$TEMP_DIR"
    exec > >(tee "$LOG_FILE") 2>&1
    trap cleanup EXIT
    echo -e "${BLUE}>>> 开始钉钉安装 (模式: $INSTALL_MODE)${RESET}"
    
    # 新增：检查是否有本地DEB文件参数
    if [ -f "$1" ] && [[ "$1" == *.deb ]]; then
        LOCAL_DEB="$1"
        INSTALL_MODE="local-deb"
    fi
}

# 新增：处理本地DEB文件
use_local_deb() {
    echo -e "${GREEN}>>> 使用本地DEB文件: $LOCAL_DEB${RESET}"
    cp "$LOCAL_DEB" "$TEMP_DIR/dingtalk-local.deb"
    DINGTALK_VER=$(dpkg -I "$LOCAL_DEB" | grep Version | awk '{print $2}')
}

download_pkg() {
    [ -n "$LOCAL_DEB" ] && return 0  # 如果使用本地文件则跳过下载
    
    local pkg_type=$1
    echo -e "${BLUE}>>> 获取钉钉最新版本...${RESET}"
    [ "$DINGTALK_VER" = "latest" ] && \
        DINGTALK_VER=$(get_latest_version)
    local base_url="https://dtapp-pub.dingtalk.com/dingtalk-desktop/x/linux/installer/linux_x64"
    local pkg_name="dingtalk-${DINGTALK_VER}.${pkg_type}"
    local download_url="${base_url}/${pkg_name}"
    
    echo -e "${YELLOW}>>> 下载: $download_url${RESET}"
    if ! wget -q --show-progress -O "$TEMP_DIR/$pkg_name" "$download_url"; then
        echo -e "${RED}下载失败！请尝试其他安装模式。${RESET}"
        return 1
    fi
    echo -e "${GREEN}>>> 下载完成: $(ls -sh "$TEMP_DIR/$pkg_name")${RESET}"
}

main() {
    init "$@"  # 传递参数给init函数
    
    install_deps
    
    case "$INSTALL_MODE" in
        "local-deb") use_local_deb && install_via_deb ;;
        "auto")
            echo -e "${BLUE}>>> 尝试自动选择最佳安装方式...${RESET}"
            if install_via_rpm; then
                echo -e "${GREEN}→ 使用官方RPM包安装成功${RESET}"
            elif install_via_deb; then
                echo -e "${GREEN}→ 通过DEB转换安装成功${RESET}"
            else
                echo -e "${YELLOW}→ 尝试Flatpak安装...${RESET}"
                install_via_flatpak
            fi
            ;;
        "rpm") install_via_rpm ;;
        "deb") install_via_deb ;;
        "flatpak") install_via_flatpak ;;
        *) echo -e "${RED}未知安装模式！${RESET}"; exit 1 ;;
    esac
    
    verify_install
}

# 其他函数保持不变（cleanup, cmd_exists, get_latest_version, install_deps, install_via_deb, install_via_rpm, install_via_flatpak, verify_install）

main "$@"

