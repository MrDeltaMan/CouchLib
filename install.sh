#!/bin/bash

echo "Iniciando a instalação do CouchLib..."
echo "======================================"

# 1. Instala dependências nativas dependendo da distro
if command -v apt &> /dev/null; then
    echo "Distro baseada em Debian/Ubuntu detectada."
    sudo apt update && sudo apt install -y mpv ffmpeg python3-venv
elif command -v pacman &> /dev/null; then
    echo "Distro baseada em Arch detectada."
    sudo pacman -Syu --noconfirm mpv ffmpeg python
elif command -v dnf &> /dev/null; then
    echo "Distro baseada em Fedora detectada."
    sudo dnf install -y mpv ffmpeg python3
elif command -v zypper &> /dev/null; then
    echo "Distro baseada em openSUSE detectada."
    sudo zypper install -y mpv ffmpeg python3
else
    echo "Gerenciador de pacotes não reconhecido. Instale mpv e ffmpeg manualmente."
fi

# 2. Criação da Estrutura de Diretórios
INSTALL_DIR="$HOME/.local/share/CouchLib"
mkdir -p "$INSTALL_DIR/src"

# Copia os arquivos do repositório para a pasta do sistema
echo "Copiando arquivos..."
cp -r src/* "$INSTALL_DIR/src/"
cp requirements.txt "$INSTALL_DIR/"

# 3. Configuração do Ambiente Virtual (venv)
echo "Criando ambiente virtual e instalando dependências Python..."
python3 -m venv "$INSTALL_DIR/venv"
source "$INSTALL_DIR/venv/bin/activate"
pip install -r "$INSTALL_DIR/requirements.txt"

# 4. Criação do Atalho de Aplicativo (.desktop)
echo "Criando atalho no menu de aplicativos..."
DESKTOP_FILE="$HOME/.local/share/applications/CouchLib.desktop"

cat <<EOF > "$DESKTOP_FILE"
[Desktop Entry]
Name=CouchLib
Comment=Gerenciador de Vídeos com Gamepad
Exec=sh -c 'env QT_QPA_PLATFORM=xcb "$INSTALL_DIR/venv/bin/python3" "$INSTALL_DIR/src/main.py"'
Icon=multimedia-video-player
Terminal=false
Type=Application
Categories=AudioVideo;Player;
EOF

chmod +x "$DESKTOP_FILE"

echo "======================================"
echo "Instalação concluída com sucesso! Procure por 'CouchLib' no seu menu de aplicativos."
