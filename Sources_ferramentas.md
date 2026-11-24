# Fontes das ferramentas do MeisterCode

**Ficheiro gerado** a partir de `tools_manifest.json` (`python tool_installer.py fontes`). Não editar à mão: corrige-se o manifesto e gera-se de novo.

O pacote de distribuição não leva as ferramentas; a app instala-as a partir destas origens, com versões e SHA-256 fixos. Manifesto revisto a 2026-11-24.

## Resumo

- 46 entradas (núcleo incluído), cerca de 9573 MB depois de instaladas e 2376 MB de downloads.
- **45 instalam-se sozinhas** pelo instalador da app; 1 têm o motivo indicado («Por fazer»).
- Todas têm o repositório ou a origem indicados. Nem todos os downloads vêm do GitHub: cada endereço está escrito por extenso.

| Grupo | O que é | Entradas | Instaladas ocupam |
|---|---|---|---|
| N | Núcleo partilhado: é instalado primeiro, as ferramentas dependem dele | 5 | 1200 MB |
| A | Arquivo portátil com SHA-256 fixo | 14 | 5128 MB |
| B | Binário do site oficial do projeto (o repositório está no GitHub, o download não) | 5 | 1830 MB |
| C | Só código-fonte de um commit fixo do GitHub (não é um executável instalado) | 5 | 468 MB |
| D | Pacote Python no ambiente partilhado (PyPI) | 9 | 837 MB |
| E | Acrescentadas a pedido do utilizador (19/11/2026): só descarregadas, ainda sem integração na app | 8 | 110 MB |

## Grupo N — Núcleo partilhado: é instalado primeiro, as ferramentas dependem dele

### 7-Zip 26.05 (núcleo)

Extrai arquivos .7z, instaladores e pacotes .zst. Serve o próprio instalador: várias ferramentas da lista só se instalam com ele.

- Pasta: `Ferramentas/_Runtime/7zip` · instalada ocupa: 8 MB · versão: 26.05
- Origem: <https://github.com/ip7z/7zip>
- Instalação pela app: **automática**
- Licença: LGPL-2.1 + restrição unRAR
- Download — 7zr.exe (< 1 MB): <https://github.com/ip7z/7zip/releases/download/26.05/7zr.exe>  
  SHA-256 `9bf582b894dfa665f852d7e9112b02290a1c303c2d95a21fcdc41ffcb03143b7` (confirmado pelo editor)
- Download — 7z2605-x64.exe (2 MB): <https://github.com/ip7z/7zip/releases/download/26.05/7z2605-x64.exe>  
  SHA-256 `fd99e86f57d8f429ef5ed045bf98315af962e2309b0f1ba87a147a44c71647d0` (confirmado pelo editor)
- Passo local — desempacotar o 7-Zip completo (`sevenzip-setup`)
- Nota: Extrai os arquivos .7z, os instaladores NSIS e os pacotes .zst. O instalador do 7-Zip é desempacotado com o 7zr.exe, não é executado.

### Node 24.22.1 (núcleo)

Motor que corre programas JavaScript. Serve para os servidores LSP (erros e navegação no código) e para as ferramentas feitas em Node.

- Pasta: `Ferramentas/_Runtime/node` · instalada ocupa: 102 MB · versão: 24.22.1
- Origem: <https://github.com/nodejs/node>
- Instalação pela app: **automática**
- Licença: MIT
- Download — Node 24.22.1 (36 MB): <https://nodejs.org/dist/v24.22.1/node-v24.22.1-win-x64.zip>  
  SHA-256 `d2046d28c2c3dcd211ac5145c0bf30e2047ef9dfb306693c8c6e2eccd8b95fa5` (do ficheiro descarregado; sem confirmação do editor)
- Nota: Corre os servidores LSP e o ImageMagick MCP. Numa instalação antiga, o Node que está dentro do REA serve para o mesmo.

### Python 3.13.18 autónomo (núcleo)

Python próprio das ferramentas, separado do Python do sistema. Serve para correr as ferramentas feitas em Python sem mexer no teu PC.

- Pasta: `Ferramentas/_Runtime/python` · instalada ocupa: 123 MB · versão: 3.13.18+20261026
- Origem: <https://github.com/astral-sh/python-build-standalone>
- Instalação pela app: **automática**
- Licença: PSF-2.0
- Download — Python 3.13.18 (21 MB): <https://github.com/astral-sh/python-build-standalone/releases/download/20261026/cpython-3.13.18%2B20261026-x86_64-pc-windows-msvc-install_only_stripped.tar.gz>  
  SHA-256 `7369f7a35f261222a6ac8b3a87c1c88eeebee8af945d85346202591a64038dd3` (confirmado pelo editor)
- Nota: Python próprio das ferramentas; não toca no Python do sistema.

### Pacotes Python partilhados (núcleo, 112 pacotes)

Bibliotecas Python que as ferramentas partilham (porta série, CAN, Modbus, imagem, rádio, etc.). Sem elas, as ferramentas do grupo D não arrancam.

- Pasta: `Ferramentas/_Runtime/pacotes` · instalada ocupa: 731 MB
- Origem: <https://pypi.org>
- Instalação pela app: **automática**
- Licença: várias (uma por pacote)
- Depende de: CorePython
- Passo local — instalar os pacotes Python (`pip-wheels`)
- Downloads — 112 ficheiros (251 MB no total), cada um com SHA-256 no manifesto:

  `amaranth-0.5.10-py3-none-any.whl`, `annotated_types-0.8.0-py3-none-any.whl`, `anyio-4.16.0-py3-none-any.whl`, `apollo_fpga-1.1.1-py3-none-any.whl`, `argparse_addons-0.12.0-py3-none-any.whl`, `attrs-26.1.0-py3-none-any.whl`, `backports.functools_lru_cache-2.0.0-py2.py3-none-any.whl`, `backports_zstd-1.8.0-cp313-cp313-win_amd64.whl`, `bitstruct-8.24.0-cp313-cp313-win_amd64.whl`, `brotli-1.2.1-cp313-cp313-win_amd64.whl`, `cantools-45.1.2-py3-none-any.whl`, `certifi-2026.10.23-py3-none-any.whl`, `cffi-2.1.1-cp313-cp313-win_amd64.whl`, `charset_normalizer-3.5.2-cp313-cp313-win_amd64.whl`, `click-8.5.0-py3-none-any.whl`, `colorama-0.4.6-py2.py3-none-any.whl`, `construct-2.10.70-py3-none-any.whl`, `crccheck-1.3.1-py3-none-any.whl`, `cryptography-50.0.2-cp311-abi3-win_amd64.whl`, `cynthion-0.2.5-py3-none-any.whl`, `cython-3.3.1-cp313-cp313-win_amd64.whl`, `deprecation-2.1.0-py2.py3-none-any.whl`, `enum_tools-0.13.0-py3-none-any.whl`, `flatbuffers-25.12.19-py2.py3-none-any.whl`, `future-1.0.0-py3-none-any.whl`, `fx2-0.16-py3-none-any.whl`, `h11-0.16.0-py3-none-any.whl`, `httpcore-1.0.9-py3-none-any.whl`, `httpx-0.28.1-py3-none-any.whl`, `httpx_sse-0.4.3-py3-none-any.whl`, `idna-3.20-py3-none-any.whl`, `imageio-2.38.1-py3-none-any.whl`, `importlib_resources-7.1.0-py3-none-any.whl`, `inflate64-1.0.4-cp313-cp313-win_amd64.whl`, `jinja2-3.1.6-py3-none-any.whl`, `jschon-0.11.1-py3-none-any.whl`, `jsonschema-4.26.0-py3-none-any.whl`, `jsonschema_specifications-2025.9.1-py3-none-any.whl`, `lazy_loader-0.6-py3-none-any.whl`, `libusb1-3.4.0-py3-none-win_amd64.whl`, `libusb_package-1.0.30.0-py3-none-win_amd64.whl`, `llvmlite-0.50.0-cp313-cp313-win_amd64.whl`, `luna_soc-0.3.2-py3-none-any.whl`, `luna_usb-0.2.3-py3-none-any.whl`, `markupsafe-3.0.4-cp313-cp313-win_amd64.whl`, `mcp-1.30.0-py3-none-any.whl`, `multivolumefile-0.2.3-py3-none-any.whl`, `networkx-3.7-py3-none-any.whl`, `numba-0.68.1-cp313-cp313-win_amd64.whl`, `numpy-2.5.4-cp313-cp313-win_amd64.whl`, `onnxruntime-1.31.1-cp313-cp313-win_amd64.whl`, `packaging-26.3-py3-none-any.whl`, `pillow-13.0.0-cp313-cp313-win_amd64.whl`, `platformdirs-4.14.5-py3-none-any.whl`, `pooch-1.9.0-py3-none-any.whl`, `prompt_toolkit-3.0.53-py3-none-any.whl`, `protobuf-7.36.2-cp310-abi3-win_amd64.whl`, `psutil-7.2.2-cp37-abi3-win_amd64.whl`, `py7zr-1.1.4-py3-none-any.whl`, `pybcj-1.0.8-cp313-cp313-win_amd64.whl`, `pyccobs-0.1.1-py3-none-win_amd64.whl`, `pycparser-3.12-py3-none-any.whl`, `pycryptodomex-3.24.2-cp37-abi3-win_amd64.whl`, `pydantic-2.14.3-py3-none-any.whl`, `pydantic_core-2.50.4-cp313-cp313-win_amd64.whl`, `pydantic_settings-2.16.2-py3-none-any.whl`, `pyftdi-0.57.2-py3-none-any.whl`, `pyfwup-0.5.3-py3-none-any.whl`, `pygments-2.21.0-py3-none-any.whl`, `pygreat-2024.0.5-py3-none-any.whl`, `pyjwt-2.15.1-py3-none-any.whl`, `pymatting-1.1.16-py3-none-any.whl`, `pymodbus-3.16.2-py3-none-any.whl`, `pyppmd-1.3.1-cp313-cp313-win_amd64.whl`, `pyqt6-6.12.0-cp310-abi3-win_amd64.whl`, `pyqt6_qt6-6.12.0-py3-none-win_amd64.whl`, `pyqt6_sip-13.13.0-cp313-cp313-win_amd64.whl`, `pyreadline3-3.5.6-py3-none-any.whl`, `pyserial-3.5-py2.py3-none-any.whl`, `python_can-4.6.1-py3-none-any.whl`, `python_dotenv-1.2.4-py3-none-any.whl`, `python_multipart-0.0.33-py3-none-any.whl`, `pyusb-1.3.1-py3-none-any.whl`, `pyvcd-0.4.2-py3-none-any.whl`, `pyvisa-1.16.2-py3-none-any.whl`, `pyvisa_py-0.8.1-py3-none-any.whl`, `pywin32-312-cp313-cp313-win_amd64.whl`, `pyxdg-0.28-py2.py3-none-any.whl`, `referencing-0.37.0-py3-none-any.whl`, `rembg-2.0.87-py3-none-any.whl`, `requests-2.34.2-py3-none-any.whl`, `rfc3986-2.0.0-py2.py3-none-any.whl`, `rpds_py-2026.9.1-cp313-cp313-win_amd64.whl`, `scikit_image-0.26.0-cp313-cp313-win_amd64.whl`, `scipy-1.18.1-cp313-cp313-win_amd64.whl`, `setuptools-84.2.1-py3-none-any.whl`, `sse_starlette-3.6.0-py3-none-any.whl`, `starlette-1.10.0-py3-none-any.whl`, `tabulate-0.10.0-py3-none-any.whl`, `textparser-0.26.2-py3-none-any.whl`, `texttable-1.7.2-py2.py3-none-any.whl`, `tifffile-2026.10.15-py3-none-any.whl`, `tomli-2.5.0-cp313-cp313-win_amd64.whl`, `tqdm-4.70.1-py3-none-any.whl`, `typing_extensions-4.16.0-py3-none-any.whl`, `typing_inspection-0.4.5-py3-none-any.whl`, `urh-2.10.0-cp313-cp313-win_amd64.whl`, `urllib3-2.8.0-py3-none-any.whl`, `usb_protocol-0.9.2-py3-none-any.whl`, `uvicorn-0.54.0-py3-none-any.whl`, `wcwidth-0.9.4-cp310-abi3-win_amd64.whl`, `wrapt-1.17.3-cp313-cp313-win_amd64.whl`

- Nota: Ficheiros .whl do PyPI, cada um com SHA-256, instalados sem rede e sem resolver dependências (--no-index --no-deps). Dão as ferramentas do grupo D.

### Servidores LSP (núcleo, 7 pacotes npm)

Servidores de linguagem para Python, JavaScript/TypeScript, HTML, CSS, JSON, Bash, YAML e PHP. Dão ao agente os erros reais do código, definições e referências.

- Pasta: `Ferramentas/_Runtime/lsp` · instalada ocupa: 236 MB
- Origem: <https://registry.npmjs.org>
- Instalação pela app: **automática**
- Licença: MIT; Intelephense proprietário
- Depende de: CoreNode
- Passo local — instalar os servidores LSP (`npm-ci`)
- Nota: npm ci com o package-lock.json que vem com a app (installer/lsp): versões e integridades fixas, sem scripts de instalação.

## Grupo A — Arquivo portátil com SHA-256 fixo

### Ghidra

Desmontador e descompilador da NSA. Serve para analisar executáveis e firmware sem o código-fonte: ver funções, cadeias de texto e o código descompilado.

- Pasta: `Ferramentas/Ghidra` · instalada ocupa: 2817 MB · versão: 12.1.4
- Origem: <https://github.com/NationalSecurityAgency/ghidra>
- Instalação pela app: **automática**
- Depende de: ClassRevive
- Download — aplicação (543 MB): <https://github.com/NationalSecurityAgency/ghidra/releases/download/Ghidra_12.1.4_build/ghidra_12.1.4_PUBLIC_20260921.zip>  
  SHA-256 `ddac49f903da9d5bac833e5cc79395098b9c33cfd3279be5f31bd00387d2d4db` (confirmado pelo editor)
- Nota: Precisa de um JDK 21 (usa o do ClassRevive).

### ImHex

Editor hexadecimal com padrões e analisadores. Serve para inspecionar e editar ficheiros binários, dumps de memória e firmware byte a byte.

- Pasta: `Ferramentas/ImHex` · instalada ocupa: 305 MB · versão: 1.38.1
- Origem: <https://github.com/WerWolv/ImHex>
- Instalação pela app: **automática**
- Download — aplicação (63 MB): <https://github.com/WerWolv/ImHex/releases/download/v1.38.1/imhex-1.38.1-Windows-Portable-x86_64.zip>  
  SHA-256 `32520e57712894bc8304c4b01553223e7dda25852326184f99dfd72a09a80187` (confirmado pelo editor)

### ImageMagick

Conversor e editor de imagens pela linha de comandos. Serve para redimensionar, converter de formato, recortar e compor imagens em série.

- Pasta: `Ferramentas/ImageMagick` · instalada ocupa: 260 MB · versão: 7.1.2-35
- Origem: <https://github.com/ImageMagick/ImageMagick>
- Instalação pela app: **automática**
- Depende de: Core7Zip
- Download — aplicação (12 MB): <https://github.com/ImageMagick/ImageMagick/releases/download/7.1.2-35/ImageMagick-7.1.2-35-portable-Q16-HDRI-x64.7z>  
  SHA-256 `34db4364da26c88d6b8cc5bbc1fff22b85d00d3b399c82fe85ee4790efacbbf1` (do ficheiro descarregado; sem confirmação do editor)

### OpenOCD · JTAG / SWD

Depurador de microcontroladores por JTAG e SWD. Serve para ler e gravar a memória flash de placas e depurar firmware com uma sonda.

- Pasta: `Ferramentas/OpenOCD` · instalada ocupa: 11 MB · versão: 0.12.0-7
- Origem: <https://github.com/xpack-dev-tools/openocd-xpack>
- Instalação pela app: **automática**
- Download — aplicação (3 MB): <https://github.com/xpack-dev-tools/openocd-xpack/releases/download/v0.12.0-7/xpack-openocd-0.12.0-7-win32-x64.zip>  
  SHA-256 `6bfd3c97135aafef8affc9af1acf34fd0e2b9ca26044506f6abd7f95b7630052` (confirmado pelo editor)

### rtl_433

Descodificador de rádio para recetores RTL-SDR. Serve para captar e interpretar sensores sem fios a 433/868 MHz (estações meteorológicas, comandos, alarmes).

- Pasta: `Ferramentas/RTL433` · instalada ocupa: 6 MB · versão: 25.12
- Origem: <https://github.com/merbanan/rtl_433>
- Instalação pela app: **automática**
- Download — aplicação (2 MB): <https://github.com/merbanan/rtl_433/releases/download/25.12/rtl_433-win-x64-25.12.zip>  
  SHA-256 `ed42651d2a2a94f6419f7675955bd65449d8247e27822c65c363595b715b7de6` (confirmado pelo editor)

### Packetry · Cynthion

Analisador de tráfego USB para a placa Cynthion. Serve para capturar e ver, pacote a pacote, a conversa entre um dispositivo USB e o computador.

- Pasta: `Ferramentas/Packetry` · instalada ocupa: 127 MB · versão: 0.5.0
- Origem: <https://github.com/greatscottgadgets/packetry>
- Instalação pela app: **automática**
- Download — aplicação (15 MB): <https://github.com/greatscottgadgets/packetry/releases/download/v0.5.0/Packetry-Installer-for-Windows.zip>  
  SHA-256 `63b4bb880b188a0cd3003f6450bca1137dbf60cd76f5f823b4ba5b11d7521e81` (confirmado pelo editor)
- Passo local — desempacotar o MSI (sem instalar no sistema) (`msi-extract`)
- Nota: O zip traz o instalador oficial; precisa do hardware Cynthion e do driver USB.

### SerialSniffer

Monitor de portas série. Serve para ver e registar o que passa numa porta COM entre um programa e um equipamento.

- Pasta: `Ferramentas/SerialSniffer` · instalada ocupa: 87 MB · versão: 1.2
- Origem: <https://github.com/DataAcquisitionTechnologies/serial-port-monitor>
- Instalação pela app: **automática**
- Download — aplicação (43 MB): <https://github.com/DataAcquisitionTechnologies/serial-port-monitor/releases/download/v1.2/SerialSniffer_V1.2.exe>  
  SHA-256 `ed5447a548765cfbd206708fa452d2c67d20251ca5cf83f9ca2fb075d6efc932` (confirmado pelo editor)
- Nota: Para intercalar outra aplicação precisa do par de portas virtuais com0com (não incluído).

### ClassRevive (adaptador da app)

Descompilador de Java com quatro motores, incluído com um JDK 21. Serve para identificar, inspecionar e descompilar ficheiros .class, JAR e APK; o JDK é usado também pelo Ghidra e pelo REA.

- Pasta: `Ferramentas/ClassRevive` · instalada ocupa: 554 MB · versão: 0.1.0
- Origem: <https://github.com/t1zzo/classrevive>
- Instalação pela app: **automática**
- Download — classrevive-0.1.0.zip (14 MB): <https://github.com/t1zzo/classrevive/releases/download/v0.1.0/classrevive-0.1.0.zip>  
  SHA-256 `1362edbca3110f5ee9090b718623d6f9ad2736fb039cbb4fef4da01cf51235c5` (confirmado pelo editor)
- Download — OpenJDK21U-jdk_x64_windows_hotspot_21.0.13_9.zip (196 MB): <https://github.com/adoptium/temurin21-binaries/releases/download/jdk-21.0.13%2B9/OpenJDK21U-jdk_x64_windows_hotspot_21.0.13_9.zip>  
  SHA-256 `a4dbaa05fca4bd89d84584e58c459bd732efebb1722af80ab13c6516832004f9` (confirmado pelo editor)
- Nota: Inclui o JDK 21 (Temurin), que o Ghidra, o REA e o Android RE também usam.

### Android Reverse Engineering

Skill de engenharia inversa de Android, com guia e scripts (jadx, Vineflower, dex2jar). Serve para descompilar APK/XAPK/JAR/AAR e procurar os endereços HTTP que a aplicação usa.

- Pasta: `Ferramentas/AndroidReverseEngineering` · instalada ocupa: 187 MB · versão: 0c7cf89830993df7dfc178498f69952262808bea
- Origem: <https://github.com/SimoneAvogadro/android-reverse-engineering-skill>
- Instalação pela app: **automática**
- Depende de: ClassRevive
- Download — source-0c7cf898.zip (—): <https://codeload.github.com/SimoneAvogadro/android-reverse-engineering-skill/zip/0c7cf89830993df7dfc178498f69952262808bea>  
  SHA-256 `4800fb58e33f35e998389d33e66b5e2fb5c2cd1ea4ad17c8f5841983c5c8619c` (do ficheiro descarregado; sem confirmação do editor)
- Download — jadx-1.5.6.zip (69 MB): <https://github.com/skylot/jadx/releases/download/v1.5.6/jadx-1.5.6.zip>  
  SHA-256 `545ea2be9c242511bc145755cf4bda2485ade42966e096f8b4d3da2a230e8974` (confirmado pelo editor)
- Download — vineflower-1.12.0.jar (2 MB): <https://github.com/Vineflower/vineflower/releases/download/1.12.0/vineflower-1.12.0.jar>  
  SHA-256 `1dfcfe974395734fa467ce620661c7623d05ba83670de0529b1fbd63ff548b9d` (confirmado pelo editor)
- Download — dex-tools-v2.4.zip (18 MB): <https://github.com/pxb1988/dex2jar/releases/download/v2.4/dex-tools-v2.4.zip>  
  SHA-256 `ee7c45eb3c1d2474a6145d8d447e651a736a22d9664b6d3d3be5a5a817dda23a` (do ficheiro descarregado; sem confirmação do editor)
- Nota: Usa o JDK do ClassRevive. Dois dos quatro ficheiros não têm hash publicado pelo autor.

### REA

Reverse Engineer Anything: agentes de engenharia inversa em Node. Serve para analisar aplicações, JavaScript/Electron, .NET, capturas HAR e binários.

- Pasta: `Ferramentas/REA` · instalada ocupa: 239 MB · versão: 6.8.0
- Origem: <https://github.com/morluto/rea>
- Instalação pela app: **automática**
- Download — Node 24.22.1 (36 MB): <https://nodejs.org/dist/v24.22.1/node-v24.22.1-win-x64.zip>  
  SHA-256 `d2046d28c2c3dcd211ac5145c0bf30e2047ef9dfb306693c8c6e2eccd8b95fa5` (do ficheiro descarregado; sem confirmação do editor)
- Passo local — instalar o pacote rea-agents 6.8.0 (`npm-ci`)
- Nota: Pacote npm rea-agents 6.8.0 (npm ci com o package-lock.json que vem com a app, sem scripts) e Node próprio. As análises com Ghidra e Java usam o Ghidra e o JDK do ClassRevive, se estiverem instalados.

### Whisper (voz para texto, local)

Reconhecimento de fala a correr no teu PC (whisper.cpp). Serve para ditares as instruções ao agente pelo microfone, sem o áudio sair do computador.

- Pasta: `Ferramentas/Whisper` · instalada ocupa: 215 MB · versão: 1.9.5
- Origem: <https://github.com/ggml-org/whisper.cpp>
- Instalação pela app: **automática**
- Licença: MIT
- Download — whisper.cpp 1.9.5 para Windows x64 (9 MB): <https://github.com/ggml-org/whisper.cpp/releases/download/b5454/whisper-bin-x64.zip>  
  SHA-256 `6ba69e3482d7826214f90a6a9c84ca07782aec1e1d0c6a7c30c994fd5d816ccb` (confirmado pelo editor)
- Download — modelo small (q5_1), multilingue (181 MB): <https://huggingface.co/ggerganov/whisper.cpp/resolve/5359861c739e955e79d9a303bcbc70fb988958b1/ggml-small-q5_1.bin>  
  SHA-256 `ae85e4a935d7a567bd102fe55afc16bb595bdb618e11b2fc7591bc08120411bb` (confirmado pelo editor)
- Nota: Binário de CPU (sem placa gráfica) e modelo multilingue «small» quantizado, do repositório do autor no Hugging Face. O modelo pode ser trocado por outro ggml-*.bin posto na pasta models.

### Piper (texto para voz, local)

Voz portuguesa a correr no teu PC. Serve para a conversa por voz: a app lê as respostas em voz alta sem o texto sair do computador.

- Pasta: `Ferramentas/Piper` · instalada ocupa: 175 MB · versão: 1.8.0
- Origem: <https://github.com/OHF-Voice/piper1-gpl>
- Instalação pela app: **automática**
- Licença: GPL-3.0-or-later (programa, corre à parte da app); voz «miro» CC BY-NC-ND 4.0 (uso não comercial); voz «tugão» treinada com dados CC0
- Depende de: CorePackages
- Download — piper-tts 1.8.0 para Windows x64 (PyPI) (33 MB): <https://files.pythonhosted.org/packages/12/9c/c736d1961cf9ce0655278731b9430df41892ca2ded7b09dabcb340612158/piper_tts-1.8.0-cp39-abi3-win_amd64.whl>  
  SHA-256 `5da9bfdb05dfe15da3536859d422e605483ffa6d2b3ec2c5b9593bae6b5aa6a4` (confirmado pelo editor)
- Download — voz pt_PT «tugão» (média) (60 MB): <https://huggingface.co/rhasspy/piper-voices/resolve/e9c8a39444359388adaa94255becb37a5a2b8e51/pt/pt_PT/tug%C3%A3o/medium/pt_PT-tug%C3%A3o-medium.onnx>  
  SHA-256 `f90d87efaa88ba0d24018f7e74a0ea3feeddeb407bf46332322a3824e9451219` (confirmado pelo editor)
- Download — configuração da voz (< 1 MB): <https://huggingface.co/rhasspy/piper-voices/resolve/e9c8a39444359388adaa94255becb37a5a2b8e51/pt/pt_PT/tug%C3%A3o/medium/pt_PT-tug%C3%A3o-medium.onnx.json>  
  SHA-256 `511b014b3baeeb7dabc0c96b35ebdc1a039e9436f6912ec94cd85e6a7a6a533e` (do ficheiro descarregado; sem confirmação do editor)
- Download — voz pt_PT «miro» (masculina, média) (61 MB): <https://huggingface.co/OpenVoiceOS/pipertts_pt-PT_miro/resolve/4ac57b67764d78838a084fd16a78504244ee26fe/miro_pt-PT.onnx>  
  SHA-256 `b7d03d4e5c51a321983b74fd5564f0ee986e17b2dc4e05cda834f9a14a149e7c` (confirmado pelo editor)
- Download — configuração da voz «miro» (< 1 MB): <https://huggingface.co/OpenVoiceOS/pipertts_pt-PT_miro/resolve/4ac57b67764d78838a084fd16a78504244ee26fe/miro_pt-PT.onnx.json>  
  SHA-256 `1cea0bbfbfe24c7a69f7029e921b4a6c9ede9527516e716a49612d10c63993d4` (do ficheiro descarregado; sem confirmação do editor)
- Nota: Pacote Python piper-tts do PyPI (só CPU), desempacotado na pasta da ferramenta e corrido com o Python das ferramentas, e duas vozes de Portugal: «miro» (masculina, do OpenVoiceOS no Hugging Face; licença só para uso não comercial) e «tugão» (do repositório de vozes do Piper). A voz escolhe-se em Configurações → Aparência. Outra voz .onnx (com o seu .onnx.json) pode ser posta na pasta voices.

### clangd (C/C++ · LSP)

Servidor de linguagem para C e C++. Serve para a app mostrar erros e avisos nos ficheiros .c/.cpp/.h e para o agente os consultar com lsp_diagnosticos.

- Pasta: `Ferramentas/Clangd` · instalada ocupa: 95 MB · versão: 23.1.0
- Origem: <https://github.com/clangd/clangd>
- Instalação pela app: **automática**
- Licença: Apache-2.0 WITH LLVM-exception
- Download — clangd 23.1.0 para Windows (28 MB): <https://github.com/clangd/clangd/releases/download/23.1.0/clangd-windows-23.1.0.zip>  
  SHA-256 `23412a240756a162e7b98a282f36aa2a23a88db5ce16a0cbc4fef7253768c810` (confirmado pelo editor)
- Nota: Usado diretamente pela app; não precisa de estar no PATH.

### rust-analyzer (Rust · LSP)

Servidor de linguagem para Rust. Serve para a app mostrar erros e avisos nos ficheiros .rs. Só é útil com o Rust (cargo) instalado no PC.

- Pasta: `Ferramentas/RustAnalyzer` · instalada ocupa: 50 MB · versão: 2026-11-16
- Origem: <https://github.com/rust-lang/rust-analyzer>
- Instalação pela app: **automática**
- Licença: MIT OR Apache-2.0
- Download — rust-analyzer 2026-11-16 para Windows x64 (17 MB): <https://github.com/rust-lang/rust-analyzer/releases/download/2026-11-16/rust-analyzer-x86_64-pc-windows-msvc.zip>  
  SHA-256 `dbf0c36ec54cf727d34cc40c9994fe71b7d52e3c28a3112c3deca1aba46fbc8f` (confirmado pelo editor)
- Nota: Usado diretamente pela app; não precisa de estar no PATH. Para analisar um projeto precisa do cargo, que vem com o Rust (rustup) e não é instalado pela app.

## Grupo B — Binário do site oficial do projeto (o repositório está no GitHub, o download não)

### GIMP + MCP

Editor de imagem completo, com ligação MCP à app. Serve para o agente editar imagens com camadas, filtros e seleções, como num editor de fotografia.

- Pasta: `Ferramentas/GIMP` · instalada ocupa: 993 MB · versão: 3.2.8
- Origem: <https://github.com/gimp-mcp/gimp-mcp>
- Instalação pela app: **automática**
- Depende de: CorePython, CorePackages
- Passo local — correr o instalador oficial do GIMP (silencioso, por utilizador) (`setup-exe`)
- Download — código-fonte (commit 73258653) (—): <https://codeload.github.com/gimp-mcp/gimp-mcp/zip/7325865385541a01aaf336ebc93b00332297f77f>  
  SHA-256 `e4a4c1a4f34464bfb15c4ab1cde057f51c125478e8c5f9821f7cff387b3f88e2` (do ficheiro descarregado; sem confirmação do editor)
- Passo local — copiar o plugin MCP para o perfil do GIMP (`copy-file`)
- Download — aplicação (177 MB): <https://mirrors.ukfast.co.uk/sites/gimp.org/pub/gimp/v3.2/windows/gimp-3.2.8-setup.exe>  
  SHA-256 `1d78874295661d791eaf149982e9b3564888631ea29186da5ff99e8114020a5b`
- Nota: É a única ferramenta em que se EXECUTA o instalador de terceiros (o oficial do GIMP, já conferido pelo SHA-256), em modo silencioso e por utilizador: regista o GIMP na conta do Windows (entrada de desinstalação). Inclui o plugin do servidor MCP.

### Wireshark / TShark / USBPcap

Analisador de tráfego de rede (com o TShark para a linha de comandos). Serve para capturar e inspecionar pacotes de rede e, com o USBPcap, de USB.

- Pasta: `Ferramentas/Wireshark` · instalada ocupa: 491 MB · versão: 4.6.9
- Origem: <https://github.com/wireshark/wireshark>
- Instalação pela app: **automática**
- Depende de: Core7Zip
- Download — aplicação (103 MB): <https://www.wireshark.org/download/win64/all-versions/WiresharkPortable64_4.6.9.paf.exe>  
  SHA-256 `71bcfda9eefec8088faaf0b8e6d026369ea83ae6149cd0b76ccf0b3194240db0` (do ficheiro descarregado; sem confirmação do editor)
- Nota: Versão portátil de wireshark.org. A captura USB exige o driver USBPcap, que não é instalado.

### sigrok-cli + descodificadores

Programa de linha de comandos para analisadores lógicos, com descodificadores de protocolos. Serve para capturar sinais digitais e descodificar I²C, SPI, UART e outros.

- Pasta: `Ferramentas/Sigrok` · instalada ocupa: 90 MB · versão: 0.7.2
- Origem: <https://github.com/sigrokproject/sigrok-cli>
- Instalação pela app: **automática**
- Depende de: Core7Zip
- Download — aplicação (37 MB): <https://sigrok.org/download/binary/sigrok-cli/sigrok-cli-0.7.2-x86_64-installer.exe>  
  SHA-256 `27ddf838c992381f3d9c52ad9d5a7ec7db382d9aea1905d44538a7c7bd368446` (do ficheiro descarregado; sem confirmação do editor)
- Nota: Instalador de sigrok.org extraído sem executar. Precisa de driver WinUSB conforme o analisador lógico.

### PulseView

Interface gráfica do sigrok. Serve para ver no ecrã os sinais captados por um analisador lógico e descodificá-los visualmente.

- Pasta: `Ferramentas/PulseView` · instalada ocupa: 103 MB · versão: 0.4.2
- Origem: <https://github.com/sigrokproject/pulseview>
- Instalação pela app: **automática**
- Depende de: Core7Zip
- Download — aplicação (42 MB): <https://sigrok.org/download/binary/pulseview/pulseview-0.4.2-64bit-static-release-installer.exe>  
  SHA-256 `63e9ba060bec76bca7e87bc7e06fd5f7405bc6c74aa0afd76e9e9b7b1c9fab41` (do ficheiro descarregado; sem confirmação do editor)
- Nota: Instalador de sigrok.org extraído sem executar.

### flashrom · CH341A

Leitor e gravador de chips de memória flash. Serve para ler, apagar e gravar BIOS e memórias SPI com um programador como o CH341A.

- Pasta: `Ferramentas/Flashrom` · instalada ocupa: 153 MB · versão: MSYS2 1.8.0
- Origem: <https://github.com/flashrom/flashrom>
- Instalação pela app: **automática**
- Depende de: Core7Zip
- Download — flashrom-1.8.0-1 (< 1 MB): <https://mirror.msys2.org/mingw/ucrt64/mingw-w64-ucrt-x86_64-flashrom-1.8.0-1-any.pkg.tar.zst>  
  SHA-256 `6645726f46a620f22d6f5cf950f70cd88d0168d3dd26bdf04c7e580377466f4c` (do ficheiro descarregado; sem confirmação do editor)
- Download — libftdi-1.5-13 (< 1 MB): <https://mirror.msys2.org/mingw/ucrt64/mingw-w64-ucrt-x86_64-libftdi-1.5-13-any.pkg.tar.zst>  
  SHA-256 `d939da4dcee7f6e9c2658b293746aeefd757c10bbe39c181deff85368aa64368` (do ficheiro descarregado; sem confirmação do editor)
- Download — libgcc-16.2.0-6 (< 1 MB): <https://mirror.msys2.org/mingw/ucrt64/mingw-w64-ucrt-x86_64-libgcc-16.2.0-6-any.pkg.tar.zst>  
  SHA-256 `80b2497f019977dd9528b1abc8621b1328a0115ab1f724047ccbb56bf323f11d` (do ficheiro descarregado; sem confirmação do editor)
- Download — libiconv-1.19.1-1 (< 1 MB): <https://mirror.msys2.org/mingw/ucrt64/mingw-w64-ucrt-x86_64-libiconv-1.19.1-1-any.pkg.tar.zst>  
  SHA-256 `8a45dc317a285a036bddd79e01505d67b79e44ff49fc3f6e7177a5ea98d098cf` (do ficheiro descarregado; sem confirmação do editor)
- Download — libstdc++-16.2.0-6 (< 1 MB): <https://mirror.msys2.org/mingw/ucrt64/mingw-w64-ucrt-x86_64-libstdc%2B%2B-16.2.0-6-any.pkg.tar.zst>  
  SHA-256 `33c5e58a85a538cf843a8672991cce591f0231d66da3b66a57629712d64be17f` (do ficheiro descarregado; sem confirmação do editor)
- Download — libusb-1.0.30-1 (< 1 MB): <https://mirror.msys2.org/mingw/ucrt64/mingw-w64-ucrt-x86_64-libusb-1.0.30-1-any.pkg.tar.zst>  
  SHA-256 `20106e6ff31b4581bb111b28a68b6b79a50dc3e5fc3033944e1c4b3ff8cd812e` (do ficheiro descarregado; sem confirmação do editor)
- Download — libwinpthread-14.0.0.r598.ge3d18511f-1 (< 1 MB): <https://mirror.msys2.org/mingw/ucrt64/mingw-w64-ucrt-x86_64-libwinpthread-14.0.0.r598.ge3d18511f-1-any.pkg.tar.zst>  
  SHA-256 `c35d6be83d141c8cfbb61f1637dd4b53aac8f5562d766aa26d0741c40bad4e4d` (do ficheiro descarregado; sem confirmação do editor)
- Download — openssl-3.6.5-1 (8 MB): <https://mirror.msys2.org/mingw/ucrt64/mingw-w64-ucrt-x86_64-openssl-3.6.5-1-any.pkg.tar.zst>  
  SHA-256 `773e021ebad83f14b5c103db467411e8ff064663e1c7e7f730e2be72f4117064` (do ficheiro descarregado; sem confirmação do editor)
- Nota: Oito pacotes do MSYS2 (flashrom 1.8.0 e as bibliotecas de que precisa), descomprimidos para app/ucrt64. Precisa do driver do CH341A.

## Grupo C — Só código-fonte de um commit fixo do GitHub (não é um executável instalado)

### Glasgow

Software da placa Glasgow, uma interface digital programável. Serve para falar com hardware por JTAG, SPI, I²C, UART e outros protocolos.

- Pasta: `Ferramentas/Glasgow` · instalada ocupa: 175 MB
- Origem: <https://github.com/GlasgowEmbedded/glasgow>
- Instalação pela app: **automática**
- Depende de: CorePython, CorePackages
- Download — código-fonte (commit cc9a083c) (—): <https://codeload.github.com/GlasgowEmbedded/glasgow/zip/cc9a083c827ba729d390c925af2af1e07ee1de97>  
  SHA-256 `f243f3e04e0b111be9ded002d2ed5fd2051e5191b2ac61ab80ec989a69e71e46` (do ficheiro descarregado; sem confirmação do editor)
- Passo local — instalar o pacote Python glasgow a partir do código (`pip-source`)
- Nota: Também há o pacote Python glasgow no ambiente partilhado. Precisa da placa e do driver. O pacote Python é construído a partir do código descarregado; a construção vai buscar a ferramenta de construção ao PyPI (esse passo não tem versão fixa).

### Lemon Serial Monitor

Monitor de portas série com driver de kernel. Serve para espiar a comunicação série de outro programa sem a interromper.

- Pasta: `Ferramentas/Lemon` · instalada ocupa: 124 MB · versão: 0.1.1
- Origem: <https://github.com/qingningmneg/LemonSerialMonitor>
- Instalação pela app: **automática**
- Download — código-fonte (commit 139de537) (—): <https://codeload.github.com/qingningmneg/LemonSerialMonitor/zip/139de5373a28db3a9a378fa3560dafe947c60ff7>  
  SHA-256 `b18dbfc4d4e4a5895899a7f17503d63645e0cf21348e5ad3afa8396b83329cfb` (do ficheiro descarregado; sem confirmação do editor)
- Download — instalador oficial (v0.1.1), só descarregado (118 MB): <https://github.com/qingningmneg/LemonSerialMonitor/releases/download/v0.1.1/LemonSerialMonitor-Setup-x64.exe>  
  SHA-256 `2d51c2128168e89ff405776a7ce813c30fb63885fa5ad146c321cbd0a47995f2` (confirmado pelo editor)
- Nota: Driver de kernel com assinatura de teste. A app descarrega o instalador oficial para a pasta (Lemon/instalador) mas NÃO o executa: correr o instalador e aceitar o que ele muda na segurança do Windows fica a cargo do utilizador. Depois, «Configurar executável» aponta para o LemonSerialMonitor.exe instalado.

### Universal Radio Hacker

Universal Radio Hacker. Serve para investigar protocolos de rádio desconhecidos: gravar o sinal, desmodulá-lo, descobrir o formato e voltar a emiti-lo.

- Pasta: `Ferramentas/URH` · instalada ocupa: 39 MB
- Origem: <https://github.com/jopohl/urh>
- Instalação pela app: **automática**
- Depende de: CorePackages
- Download — código-fonte (commit 1403d929) (—): <https://codeload.github.com/jopohl/urh/zip/1403d92987cc3d01d41aff64250955ce455dabd2>  
  SHA-256 `10f5018e398da95f94cd0bb4d4b14ce60387389290381bccd7a87c2059a371c7` (do ficheiro descarregado; sem confirmação do editor)
- Nota: Projeto arquivado. Também há o pacote Python urh.

### PortSniffer

Driver de filtro para portas série. Serve para registar o que um programa envia e recebe por uma porta COM.

- Pasta: `Ferramentas/PortSniffer` · instalada ocupa: 2 MB · versão: 2.1
- Origem: <https://github.com/enlyze/PortSniffer>
- Instalação pela app: **automática**
- Download — código-fonte (commit acc298db) (—): <https://codeload.github.com/enlyze/PortSniffer/zip/acc298dbb4a387e03b3404c1812f60e245738d2b>  
  SHA-256 `37a24e3067660824a59fbc7dcac2e102c4e5905f140f4912b8d69bb6f9bda9f5` (do ficheiro descarregado; sem confirmação do editor)
- Download — programa e driver (release 2.1, x64) (2 MB): <https://github.com/enlyze/PortSniffer/releases/download/2.1/ENLYZE-PortSniffer-2.1-amd64.zip>  
  SHA-256 `eaaccf9543b504fd08dd13be6acc1d3e25d1e4150272d4adea865f748e16ba33` (do ficheiro descarregado; sem confirmação do editor)
- Nota: Programa e driver publicados pelo autor (2022). A app só os põe na pasta: instalar o driver (PortSniffer-Tool.exe /install, com administrador) fica a cargo do utilizador.

### ImageMagick MCP

Servidor MCP que liga o ImageMagick à app. Serve para o agente converter e editar imagens por pedido, sem escreveres comandos.

- Pasta: `Ferramentas/ImageMagickMCP` · instalada ocupa: 128 MB · versão: 0.1.0
- Origem: <https://github.com/bthurlow/imagemagick-mcp>
- Instalação pela app: **automática**
- Depende de: CoreNode, ImageMagick
- Download — código-fonte (commit 71ad5ec8) (—): <https://codeload.github.com/bthurlow/imagemagick-mcp/zip/71ad5ec845ce4e20c3ea21025b8caf1aa29f1615>  
  SHA-256 `b66eaa816927f55d2d8fa07100f225f068ce5d643e1bead49c2a42d35abb6024` (do ficheiro descarregado; sem confirmação do editor)
- Passo local — instalar as dependências (npm ci com o bloqueio que vem com a app, sem scripts) (`npm-ci`)
- Passo local — construir o servidor (npm run build) (`npm-run`)
- Nota: Código de um commit fixo; o projeto só traz yarn.lock, por isso o package-lock.json usado é o que vem com a app (installer/imagemagick-mcp). Construção local: executa o script «build» do projeto.

## Grupo D — Pacote Python no ambiente partilhado (PyPI)

### Pillow

Biblioteca Python de imagem. Serve para o agente abrir, recortar, redimensionar e converter imagens em scripts.

- Pasta: `Ferramentas/Pillow` · instalada ocupa: 0 MB
- Origem: <https://github.com/python-pillow/Pillow>
- Instalação pela app: **automática**
- Depende de: CorePackages
- Nota: Pacote pillow.

### Remoção de fundo · rembg

Remoção de fundo por inteligência artificial, a correr no teu PC. Serve para recortar o motivo de uma fotografia e ficar com fundo transparente.

- Pasta: `Ferramentas/Rembg` · instalada ocupa: 837 MB · versão: 2.0.87
- Origem: <https://github.com/danielgatis/rembg>
- Instalação pela app: **automática**
- Depende de: CorePackages
- Download — modelo u2netp.onnx (4 MB): <https://github.com/danielgatis/rembg/releases/download/v0.0.0/u2netp.onnx>  
  SHA-256 `309c8469258dda742793dce0ebea8e6dd393174f89934733ecc8b14c76f4ddd8` (do ficheiro descarregado; sem confirmação do editor)
- Nota: Pacote rembg 2.0.87 (núcleo) + modelo ONNX u2netp. Outros modelos que tenhas posto em models/ não fazem parte da lista.

### Portas série · pySerial

Acesso a portas série (pySerial). Serve para o agente falar com placas, módulos e equipamentos ligados por USB-série ou COM.

- Pasta: `Ferramentas/Serial` · instalada ocupa: 0 MB
- Origem: <https://github.com/pyserial/pyserial>
- Instalação pela app: **automática**
- Depende de: CorePackages
- Nota: Pacote pyserial.

### Bus Pirate · terminal série

Terminal para o Bus Pirate. Serve para testar e explorar chips por I²C, SPI, UART e 1-Wire através dessa placa.

- Pasta: `Ferramentas/BusPirate` · instalada ocupa: 0 MB
- Origem: <https://github.com/DangerousPrototypes/BusPirate5-firmware>
- Instalação pela app: **automática**
- Depende de: CorePackages
- Nota: Usa pyserial; não instala firmware.

### FTDI · I²C / SPI / GPIO

Controlo de adaptadores FTDI. Serve para usar um cabo FTDI como interface I²C, SPI ou de pinos GPIO.

- Pasta: `Ferramentas/PyFtdi` · instalada ocupa: 0 MB
- Origem: <https://github.com/eblot/pyftdi>
- Instalação pela app: **automática**
- Depende de: CorePackages
- Nota: Pacote pyftdi; precisa de libusb/WinUSB. O projeto não suporta oficialmente o Windows.

### Modbus RTU / ASCII / TCP

Cliente e servidor Modbus (RTU, ASCII e TCP). Serve para ler e escrever registos de autómatos, contadores e outros equipamentos industriais.

- Pasta: `Ferramentas/Modbus` · instalada ocupa: 0 MB
- Origem: <https://github.com/pymodbus-dev/pymodbus>
- Instalação pela app: **automática**
- Depende de: CorePackages
- Nota: Pacote pymodbus.

### CAN + cantools

Barramento CAN com descodificação por ficheiros DBC (python-can e cantools). Serve para ler, enviar e interpretar mensagens de redes de automóveis e máquinas.

- Pasta: `Ferramentas/CAN` · instalada ocupa: 0 MB
- Origem: <https://github.com/hardbyte/python-can>
- Instalação pela app: **automática**
- Depende de: CorePackages
- Nota: Pacotes python-can e cantools.

### Osciloscópios · VISA / SCPI

Controlo de instrumentos de bancada por VISA/SCPI. Serve para comandar osciloscópios, fontes e multímetros e recolher as medições.

- Pasta: `Ferramentas/VISA` · instalada ocupa: 0 MB
- Origem: <https://github.com/pyvisa/pyvisa-py>
- Instalação pela app: **automática**
- Depende de: CorePackages
- Nota: Pacotes pyvisa/pyvisa-py.

### Cynthion · software de controlo

Software de controlo da placa Cynthion. Serve para configurar a placa e usá-la para analisar ou emular dispositivos USB.

- Pasta: `Ferramentas/Cynthion` · instalada ocupa: 0 MB
- Origem: <https://github.com/greatscottgadgets/cynthion>
- Instalação pela app: **automática**
- Depende de: CorePackages
- Nota: Pacote cynthion; precisa do hardware e do driver USB.

## Grupo E — Acrescentadas a pedido do utilizador (19/11/2026): só descarregadas, ainda sem integração na app

### Meshy 3D Agent (skills)

Instruções (skills) para agentes criarem modelos 3D com a plataforma Meshy. Serve para gerar um modelo 3D a partir de texto ou imagem; exige conta Meshy paga.

- Pasta: `Ferramentas/Meshy3DAgent` · instalada ocupa: 0 MB · versão: 0.9.8
- Origem: <https://github.com/meshy-dev/meshy-3d-agent>
- Instalação pela app: **automática**
- Licença: MIT
- Integração na app: **nenhuma ainda** — o instalador só descarrega e confere; o agente ainda não a usa.
- Download — código-fonte (commit 7f8e3319, 2026-11-18) (< 1 MB): <https://codeload.github.com/meshy-dev/meshy-3d-agent/zip/7f8e33196db4e9e26cbaa0da4fcc14104ccda81d>  
  SHA-256 `42ead2b3d2c8ca6efe8472146d94986f8c1d6175524afefaa53b5c063772272e` (do ficheiro descarregado; sem confirmação do editor)
- Nota: Instruções (skills) para agentes gerarem modelos 3D com a plataforma Meshy. Não traz programa: usa o Meshy CLI (Node 22.12+). Exige conta Meshy paga (Pro ou superior) e gasta créditos Meshy.

### 3D Printing · 3d-print-designer (skills + modelos OpenSCAD)

Skill e modelos paramétricos para impressão 3D. Serve para ir da descrição de uma peça ao modelo OpenSCAD e aos ficheiros STL/3MF prontos a imprimir.

- Pasta: `Ferramentas/Printing3D` · instalada ocupa: 0 MB · versão: 1.0.0
- Origem: <https://github.com/wilsonwaters/3d-printing>
- Instalação pela app: **automática**
- Licença: MIT
- Integração na app: **nenhuma ainda** — o instalador só descarrega e confere; o agente ainda não a usa.
- Download — código-fonte (commit f5e18a16, 2026-10-01) (18 MB): <https://codeload.github.com/wilsonwaters/3d-printing/zip/f5e18a16031f5a11b20f7753574ff48494891587>  
  SHA-256 `510aaf4b40714857366011e46c4c23899ff47897c87fa180d92f1c0d035dee3d` (do ficheiro descarregado; sem confirmação do editor)
- Download — pacote da release 1.0.0 (< 1 MB): <https://github.com/wilsonwaters/3d-printing/releases/download/v1.0.0/3d-print-designer.zip>  
  SHA-256 `c7c0d88a2cd5b831ce3fd3b2efc585866d39a500ca8418ce387cebd18677cdd4` (confirmado pelo editor)
- Nota: Skill que vai da descrição de uma peça ao modelo OpenSCAD, imagens, STL e 3MF, mais modelos paramétricos. Precisa do OpenSCAD instalado (não incluído).

### Wonder3D (imagem → 3D)

Modelo de IA que reconstrói um objeto 3D a partir de uma só imagem. Serve para obter uma malha 3D com textura a partir de uma fotografia; precisa de GPU e dos pesos do modelo.

- Pasta: `Ferramentas/Wonder3D` · instalada ocupa: 0 MB
- Origem: <https://github.com/xxlong0/Wonder3D>
- Instalação pela app: **automática**
- Licença: MIT
- Integração na app: **nenhuma ainda** — o instalador só descarrega e confere; o agente ainda não a usa.
- Download — código-fonte (commit d894f827, 2025-02-18) (6 MB): <https://codeload.github.com/xxlong0/Wonder3D/zip/d894f827aa8c2917761a0dad3ab40df74c7a5b24>  
  SHA-256 `43e1d8d1712c149b6cf252260c7d07f33abc68629b239efc40de5487d226e6c0` (do ficheiro descarregado; sem confirmação do editor)
- Nota: Código de investigação (CVPR 2024). Só o código é descarregado: para funcionar precisa de placa NVIDIA com CUDA, de um ambiente PyTorch próprio e dos pesos do modelo (vários GB, no Hugging Face). Sem atividade desde 03/2025.

### Hunyuan3D 2.0 (texto/imagem → 3D)

Modelo de IA da Tencent que gera modelos 3D com textura a partir de imagem ou texto. Bloqueado: a licença exclui a União Europeia.

- Pasta: `Ferramentas/Hunyuan3D2` · instalada ocupa: 0 MB
- Origem: <https://github.com/Tencent-Hunyuan/Hunyuan3D-2>
- Instalação pela app: **por fazer** — a licença exclui expressamente a União Europeia, o Reino Unido e a Coreia do Sul («THIS LICENSE AGREEMENT DOES NOT APPLY IN THE EUROPEAN UNION…»); fica por instalar até o utilizador decidir
- Licença: Tencent Hunyuan 3D 2.0 Community License
- Integração na app: **nenhuma ainda** — o instalador só descarrega e confere; o agente ainda não a usa.
- Download — código-fonte (commit f8db6309, 2025-10-28) (77 MB): <https://codeload.github.com/Tencent-Hunyuan/Hunyuan3D-2/zip/f8db63096c8282cb27354314d896feba5ba6ff8a>  
  SHA-256 `1be140879646034a98941e494072ce0ab26918fdc2fb59210443d56d41bc5622` (do ficheiro descarregado; sem confirmação do editor)
- Nota: Modelos de difusão da Tencent. Precisa de placa NVIDIA (6 a 16 GB de VRAM), ambiente PyTorch e pesos de vários GB (Hugging Face).

### PCB ReTrace (engenharia inversa de PCB no browser)

Aplicação web que corre só no browser, sem enviar dados. Serve para engenharia inversa de placas: das fotografias da placa aos componentes, às pistas e à exportação para o KiCad.

- Pasta: `Ferramentas/PcbRetrace` · instalada ocupa: 0 MB
- Origem: <https://github.com/dev-lab/pcb-retrace>
- Instalação pela app: **automática**
- Licença: AGPL-3.0 ou licença comercial (dupla)
- Integração na app: **nenhuma ainda** — o instalador só descarrega e confere; o agente ainda não a usa.
- Download — código-fonte (commit f00f3d50, 2026-11-18) (22 MB): <https://codeload.github.com/dev-lab/pcb-retrace/zip/f00f3d50f4c0f91bf90824eedfa03d62cc6c924d>  
  SHA-256 `f516c3a53fda0d75a3a72a77b82ef8a1ba9ef757805621a6ce1d6dbe87e4c0a1` (do ficheiro descarregado; sem confirmação do editor)
- Nota: Aplicação web que corre só no browser (HTML, JavaScript, WebAssembly), sem enviar dados: fotos da placa → componentes, pistas e exportação para KiCad. O código está na pasta docs/. AGPL-3.0: quem a redistribuir modificada tem de publicar o código.

### Svg2Shenzhen (Inkscape → KiCad)

Extensão do Inkscape que exporta desenhos SVG para o KiCad. Serve para fazer placas de circuito e footprints a partir de um desenho vetorial; projeto descontinuado pelo autor.

- Pasta: `Ferramentas/Svg2Shenzhen` · instalada ocupa: 0 MB · versão: 0.2.18.7
- Origem: <https://github.com/badgeek/svg2shenzhen>
- Instalação pela app: **automática**
- Licença: GPL-3.0
- Integração na app: **nenhuma ainda** — o instalador só descarrega e confere; o agente ainda não a usa.
- Download — código-fonte (commit 8ac23311, 2025-03-15) (3 MB): <https://codeload.github.com/badgeek/svg2shenzhen/zip/8ac233113a1ac6fd9a4599e3eeb6edf478a8903f>  
  SHA-256 `77020d94696e6d7dd94aa4118d7af7cd2ca3f0b2a01b1ae5da0992f57e1e5d42` (do ficheiro descarregado; sem confirmação do editor)
- Download — pacote da release 0.2.18.7 (1 MB): <https://github.com/badgeek/svg2shenzhen/releases/download/0.2.18.7-Windows-Fix/svg2shenzhen-extension-0.2.18.7.zip>  
  SHA-256 `5ab058ecf908f4bb7ae2d94436857ffad533a2e0504b70d2f4d09ac004c6d60b` (do ficheiro descarregado; sem confirmação do editor)
- Nota: Extensão do Inkscape que exporta desenhos para PCB e footprints do KiCad. Projeto descontinuado pelo autor (recomenda o Gingerbread). Precisa do Inkscape 1.0 ou superior (não incluído). O zip da extensão não tem hash publicado pelo autor.

### kicad-happy (skills de revisão KiCad)

Skills e scripts para agentes trabalharem com projetos KiCad. Serve para rever esquemas, placas e Gerbers, fazer pré-conformidade EMC e simulação SPICE.

- Pasta: `Ferramentas/KicadHappy` · instalada ocupa: 0 MB · versão: 3.0.2
- Origem: <https://github.com/aklofas/kicad-happy>
- Instalação pela app: **automática**
- Licença: MIT
- Integração na app: **nenhuma ainda** — o instalador só descarrega e confere; o agente ainda não a usa.
- Download — código-fonte (commit 6b9767e1, 2026-11-15) (3 MB): <https://codeload.github.com/aklofas/kicad-happy/zip/6b9767e19979cdef91631573753b1547efdbeab9>  
  SHA-256 `145c80972323d525491e6d189011fc7ca0885f1b6bac01b802a6442a5c44d021` (do ficheiro descarregado; sem confirmação do editor)
- Nota: Skills e scripts Python (3.10+) para rever esquemas, PCB e Gerbers do KiCad, pré-conformidade EMC e simulação SPICE. Algumas funções pedem ferramentas externas (por exemplo ngspice) e acesso à rede para folhas de dados.

### Kit de assets (captura e extração)

Scripts do utilizador para gravar o tráfego de uma página num ficheiro HAR e extrair de lá imagens, sons, vídeos, fontes e dados, com galeria local. Também separa sprites de atlas TexturePacker/Pixi.

- Pasta: `Ferramentas/KitAssets` · instalada ocupa: 110 MB
- Origem: <https://github.com/thornet2004/kit-assets>
- Instalação pela app: **automática**
- Integração na app: **nenhuma ainda** — o instalador só descarrega e confere; o agente ainda não a usa.
- Depende de: CorePackages
- Download — código-fonte (commit 60bb1cfa, 2026-11-24) (< 1 MB): <https://codeload.github.com/thornet2004/kit-assets/zip/60bb1cfaceade0ce8b83328917a747d6c69924b8>  
  SHA-256 `1b324fc67170519e6e73baed27d16d4023de17a240b0128f8b9a527e3848a1ff` (do ficheiro descarregado; sem confirmação do editor)
- Passo local — instalar o Playwright no ambiente partilhado (`pip-wheels`)
- Download — playwright 1.64.1 (37 MB): <https://files.pythonhosted.org/packages/96/0a/64db6851aa1852a4f76be28eea71d4e2bf9f3ce493ee2e66939426729046/playwright-1.64.1-py3-none-win_amd64.whl>  
  SHA-256 `5e240a79464434c9260957b9ef59a5808e02e96e3fcabdc717fd7485260b9730`
- Download — greenlet 3.5.6 (< 1 MB): <https://files.pythonhosted.org/packages/86/da/b7669b09586365654083a62bd0724cf06cb74bd5085a15cdd161271f992f/greenlet-3.5.6-cp313-cp313-win_amd64.whl>  
  SHA-256 `5b602b4201b965a8354d74e232364a66ff243dd142e350d035f46169bb36e13d`
- Download — pyee 14.0.0 (< 1 MB): <https://files.pythonhosted.org/packages/81/12/5347938b1f9a6453f0dbdfcc3e2388a1320ef9b9ec17fbefbc4ab647ea98/pyee-14.0.0-py3-none-any.whl>  
  SHA-256 `3ac2d3229a9677f7de2c33d7f52fe25b638a46b19c413fea2edc8c6d0a644e4d`
- Nota: Projeto do utilizador (24/11/2026). «extrair.py» e «separar_sprites.py» só precisam do Python e do Pillow do núcleo. «capturar.py» usa o Playwright, instalado aqui no ambiente partilhado; o navegador é o Edge do Windows (--browser msedge), não se descarrega o Chromium.

## O que nenhum instalador faz sozinho

- Drivers USB que pedem permissões de administrador: USBPcap, WinUSB, CH341A, com0com, Cynthion, Glasgow, SDR.
- O driver de kernel do Lemon (assinatura de teste).
- Os pesos dos modelos de IA (Wonder3D, Hunyuan3D): vários GB, fora desta lista.
