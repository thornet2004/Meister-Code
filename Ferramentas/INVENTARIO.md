# Bancada de ferramentas instalada

Abre **🧰 Ferramentas**, na barra superior da app. Pesquisa por nome/protocolo,
filtra por categoria ou mostra só as instaladas. O painel inclui também REA,
ClassRevive, Android Reverse Engineering, operações nativas e servidores MCP.

**Testar ligação MCP** verifica o servidor e enumera as operações, sem ligar a
hardware. **Configurar executável** permite apontar um binário já instalado.
**Abrir aplicação** inicia os editores/visualizadores, quando aplicável.
As aprovações continuam em Configurações → Ferramentas em pastas.

O modelo descobre schemas com ferramentas_pesquisar e executa por
ferramentas_executar. Não precisa de receber centenas de schemas em cada pedido.
Imagens MCP PNG/JPEG/WebP são guardadas na conversa e enviadas como imagens
ao modelo; base64 não é guardado no texto dos passos.

## Software e requisitos

| Ferramenta | Versão | Estado | Requisitos / notas |
|---|---|---|---|
| ImageMagick | 7.1.2-35 | Instalado |  |
| ImageMagick MCP | — | Instalado | Servidor MCP original compilado localmente: 57 operações. |
| Pillow | 13.0.0 | Instalado |  |
| Remoção de fundo · rembg | 2.0.87 | Instalado | Modelo u2netp instalado localmente. Inclui pré-visualização com transparência. |
| GIMP + MCP | 3.2.8 | Instalado | Editor e plugin MCP precisam de estar abertos para editar documentos GIMP. |
| Portas série · pySerial | 3.5 | Instalado | Adaptador e driver da porta COM. |
| sigrok-cli + descodificadores | 0.7.2 | Instalado | Driver compatível do analisador lógico (WinUSB, conforme equipamento). |
| PulseView | 0.4.2 | Instalado | Driver compatível do analisador lógico. |
| SerialSniffer | 1.2 | Instalado | Para intercalar outra aplicação: par COM virtual com0com e configuração das portas. |
| Bus Pirate · terminal série | 3.5 | Instalado | Selecionar porta, baud rate e protocolo da revisão do Bus Pirate; não instala firmware. |
| FTDI · I²C / SPI / GPIO | 0.57.2 | Instalado | FTDI compatível + libusb/WinUSB. Windows não é oficialmente suportado pelo projeto. |
| Modbus RTU / ASCII / TCP | 3.16.2 | Instalado | Interface RS485/RS232 ou endereço TCP. |
| CAN + cantools | 4.6.1 | Instalado | Interface CAN e respetivo driver; inclui backend virtual para testes. |
| Osciloscópios · VISA / SCPI | 1.16.2 | Instalado | Endereço VISA e comandos SCPI compatíveis com o instrumento. |
| Wireshark / TShark / USBPcap | 4.6.9 | Instalado | Captura USB exige driver USBPcap instalado; não é instalado automaticamente. |
| flashrom · CH341A | MSYS2 1.8.0 | Instalado | Executável Windows compatível + driver CH341A; confirmar tensão e pinagem antes de escrever. |
| OpenOCD · JTAG / SWD | 0.12.0-7 | Instalado | Adaptador, driver e configuração do alvo. |
| ImHex | 1.38.1 | Instalado |  |
| Binwalk | 2.3.4+dfsg1-5 | Instalado | Binwalk 2.3.4 via Ubuntu-24.04 no WSL; fonte v3 incluída separadamente. Extratores externos não incluídos. |
| Ghidra | 12.1.4 | Instalado | JDK 21+ compatível com esta versão; análises disponíveis no REA. |
| Glasgow | 0.0.0+cc9a083 | Instalado | Placa Glasgow, driver USB e toolchain para compilar gateware. |
| Cynthion · software de controlo | 0.2.5 | Instalado | Hardware Cynthion e driver USB; não atualiza firmware automaticamente. |
| Packetry · Cynthion | 0.5.0 | Instalado | Hardware Cynthion e driver USB. |
| rtl_433 | 25.12 | Instalado | Receptor SDR compatível e driver USB. |
| Lemon Serial Monitor | — | Integração preparada · dependência em falta | Driver de kernel com assinatura de teste; alterações de segurança do Windows ficam a cargo do utilizador. |
| Universal Radio Hacker | 2.10.0 | Instalado | Projeto arquivado; SDR e backend compatível. |
| PortSniffer | — | Integração preparada · dependência em falta | Driver antigo WDK 7.1; compatibilidade e assinatura têm de ser verificadas. |

## Equipamento

- RS232/TTL: portas disponíveis por pySerial; captura em loop próprio, sem
  interceptar automaticamente uma porta que outra aplicação já abriu.
- SerialSniffer: intercalar outra aplicação exige configurar um par com0com.
- I²C/SPI via FTDI: MPSSE e driver libusb/WinUSB compatíveis.
- Bus Pirate: terminal série; os comandos variam com a revisão e firmware.
- Modbus: operações de leitura RTU/ASCII/TCP; sem escrita automática.
- CAN: selecionar interface e canal; backend virtual incluído para testes.
- VISA: backend pyvisa-py; comandos SCPI dependem do modelo do instrumento.
- CH341A/JTAG/SWD/SDR/Cynthion/Glasgow: ferramentas instaladas, ligação real
  exige o driver, a revisão e a configuração do alvo. Nenhum firmware foi gravado.
- USBPcap, Lemon e PortSniffer: drivers não instalados automaticamente;
  não alterámos Secure Boot, TESTSIGNING nem certificados de drivers.

## GIMP e imagens

GIMP 3.2.8 tem um perfil privado em GIMP/profile, com o plugin original.
Abre pelo botão **Abrir aplicação**, cria/abre uma imagem e usa
Tools → MCP → Start MCP Server. O MCP expõe 79 operações.
ImageMagick MCP expõe 57 operações do servidor original compilado localmente.
Pillow e rembg usam adaptadores da app; rembg usa u2netp local em CPU.
A remoção de fundo não ativa alpha matting/JIT desnecessário.

## Binwalk e Ghidra

Binwalk operacional: pacote Ubuntu 2.3.4+dfsg1-5, em Ubuntu-24.04/WSL.
A app traduz caminhos Windows para WSL sem construir comandos de shell.
A fonte v3 está incluída, mas não foi compilada; não é apresentada como instalada.
Extratores adicionais do Binwalk não foram instalados.
Ghidra 12.1.4 é a versão configurada no REA 6.8.0 com o JDK 21 portátil.

## Reposição das dependências

A pasta Ferramentas deve acompanhar a app. O exe sozinho não transporta todos
os SDKs, editores e modelos (vários GB). Para reinstalar o runtime Python:

```powershell
$env:UV_PYTHON_INSTALL_DIR = "$PWD/Ferramentas/_Runtime/python"
uv python install 3.13
uv pip install --python Ferramentas/_Runtime/python/cpython-3.13.18-windows-x86_64-none/python.exe --target Ferramentas/_Runtime/site-packages -r requirements-bench.txt
```

Glasgow é compilado da fonte fixada em fonte.json (não usar o pacote PyPI 0.0.0).
`python install_bench.py` volta a obter os arquivos/fontes oficiais principais.
Não é um instalador de drivers nem substitui as configurações existentes.
Instalações adicionais e os respetivos resultados estão registados em tests/*.log.
