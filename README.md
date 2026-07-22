# 🛋️ CouchLib: Gerenciador de Bibliotecas de Vídeo Offline com Gamepad

**Descrição:** O CouchLib é um projeto de código aberto para Linux feito para gerenciar bibliotecas de vídeo locais. Ele foi pensado do zero para ser operado 100% com gamepads. Seguimos uma filosofia de simplicidade e conforto, sendo a ferramenta perfeita para uso em HTPCs ou simplesmente para setups que buscam baixa fricção na hora de assistir a um filme no sofá.

## 📥 Como Instalar?

1. No topo deste repositório, clique no botão verde **Code** e depois em **Download ZIP**.
2. Extraia o arquivo baixado em uma pasta de sua preferência e abra a pasta extraída.
3. Clique com o botão direito em um espaço vazio dentro da pasta, selecione "Abrir no Terminal" (ou equivalente) e rode o seguinte comando:

   ```bash
   ./install.sh
   ```

4. Após o comando, digite sua senha caso o terminal peça e aguarde a finalização da instalação.
5. Tudo pronto! Digite "CouchLib" no menu de aplicativos do seu sistema e clique no ícone para iniciar.

## 🎮 Como Usar?

O CouchLib é simples e intuitivo. Ao entrar pela primeira vez, o programa pedirá para que você selecione sua biblioteca principal. Essa será a pasta exibida logo de cara ao iniciar o programa nas próximas vezes.

* **Navegação:** Use o botão **A** (Xbox) ou **Cruz** (PlayStation) para abrir e navegar pelas pastas do seu computador.

* **Confirmar Biblioteca:** Quando estiver dentro da pasta principal onde ficam seus vídeos, pressione **Y** (Xbox) ou **Triângulo** (PlayStation) para confirmar.

*Nota:* Caso queira alterar sua biblioteca principal no futuro, o processo atualmente é manual. Feche o CouchLib, abra seu gerenciador de arquivos, vá até o caminho `~/.config/htpc-app` e delete o único arquivo de banco de dados que estiver por lá. Depois, basta abrir o CouchLib novamente.

* **Assistindo aos vídeos:** Após a configuração inicial, basta navegar pelas pastas e selecionar os vídeos que você desejar. Ao abrir um vídeo com **A / Cruz**, ele será executado automaticamente em tela cheia.

* **Menu do Player:** Para manipular o vídeo em reprodução, basta apertar qualquer direção do **D-Pad** (setinhas) do controle. Isso irá acionar o menu na tela, onde você pode pausar, retroceder, avançar, alterar a faixa de áudio e legenda, ajustar o volume, mudar o modo de reprodução e sair do vídeo. Tudo controlável pelo seu gamepad!

## 🤝 Como Posso Contribuir?

Caso tenha conhecimento em Python, o projeto está totalmente aberto para ser editado e melhorado. Após a instalação, os arquivos fonte ficam disponíveis na sua máquina no caminho:

`~/.local/share/CouchLib/src`

Lá você terá acesso aos 3 arquivos `.py` que compõem o programa e poderá testar suas alterações em tempo real.

Sinta-se livre para criar forks, experimentar ideias novas ou enviar um Pull Request (PR) aqui neste repositório. Toda contribuição é muito bem-vinda.

Agradeço desde já pela atenção e faça um bom uso do CouchLib! 🍿
