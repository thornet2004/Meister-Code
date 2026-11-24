# Ferramentas propostas para a app — pesquisa de 6 de novembro de 2026

Seleção baseada nos repositórios e documentação dos próprios projetos.
O utilizador confirmou que tem adaptadores USB-RS232/TTL, analisador lógico,
CH341A, Bus Pirate e osciloscópio. Modelos/revisões exatos ainda por identificar.
Este documento é uma proposta de integração: não instala nem ativa ferramentas.
As classificações de facilidade são avaliações para esta app, não testes de bancada.

## Imagem

| Projeto | Utilidade | Integração proposta | Requisitos/limites |
|---|---|---|---|
| [ImageMagick](https://github.com/ImageMagick/ImageMagick) | Recorte, escala, rotação, composição, conversão, canais e transparência; processamento de lotes | CLI local com operações estruturadas MCP | Distribuição Windows disponível; ideal como base de edição determinística |
| [ImageMagick MCP](https://github.com/bthurlow/imagemagick-mcp) | Servidor comunitário já preparado para automatizar ImageMagick | MCP stdio existente, a testar | Requer ImageMagick 7+ e Node; é um projeto independente do ImageMagick |
| [rembg](https://github.com/danielgatis/rembg) | Segmentação/remoção de fundo e produção de máscaras/PNG com alpha | Adaptador da app para CLI ou biblioteca, com ambiente separado | README atual exige Python >=3.11 e <3.14; a app usa 3.14, pelo que precisa de runtime próprio. Modelos locais podem ser descarregados previamente; não é necessário escolher backends cloud |
| [GIMP MCP](https://github.com/gimp-mcp/gimp-mcp) | Camadas, seleções, máscaras, texto, ajustes e exportação; previews durante a edição | MCP stdio existente + plugin GIMP | README exige GIMP 3.2+ e Python 3.11+. É necessário iniciar o bridge no GIMP. A app precisa de passar imagens MCP ao modelo para este verificar visualmente o resultado |

Recomendação: ImageMagick e rembg primeiro, seguidos de GIMP para edição por
camadas. A remoção automática de fundo requer inspeção do resultado; o nome
de uma operação não garante qualidade nos contornos ou fidelidade de um logo.

## RS232/UART e aquisição lógica

| Projeto | Utilidade | Integração proposta | Compatibilidade/limites |
|---|---|---|---|
| [pySerial](https://github.com/pyserial/pyserial) | Enumerar portas COM, configurar baud/paridade, ler, escrever e guardar dados binários/hex com timestamps | Adaptador MCP Python; sessões e capturas em background | Windows suportado. Abre uma porta série; não interceta automaticamente uma porta já ocupada por outra aplicação |
| [sigrok-cli](https://github.com/sigrokproject/sigrok-cli) + [PulseView](https://github.com/sigrokproject/pulseview) + [libsigrokdecode](https://github.com/sigrokproject/libsigrokdecode) | Aquisição e descodificação de UART, I²C, SPI e numerosos protocolos; análise de capturas offline e interface gráfica | sigrok-cli como motor para a app; PulseView para inspeção visual | Confirmar o modelo do analisador, o driver e os canais/níveis usados. Os repositórios GitHub são mirrors do projeto sigrok |
| [SerialSniffer](https://github.com/DataAcquisitionTechnologies/serial-port-monitor) | Ver TX/RX entre um programa de PC e um dispositivo, em hex/ASCII, com exportação CSV e vista SCPI | Adaptar o núcleo Python ou importar os CSVs | Windows 10/11; exige par virtual com0com e reconfigurar a aplicação original para esse par. É uma ponte de encaminhamento: pode influenciar temporização, embora preserve os bytes |
| [Bus Pirate 5/6](https://github.com/DangerousPrototypes/BusPirate5-firmware) | Comunicar com chips por I²C, SPI, UART e 1-Wire; controlo do equipamento já existente | Adaptador MCP sobre o protocolo série documentado | Identificar a geração/revisão do Bus Pirate: protocolos de automação e comandos variam. Captura passiva e controlo ativo devem ser operações distintas |
| [PyFtdi](https://github.com/eblot/pyftdi) | SPI/I²C/GPIO e JTAG básico com interfaces FTDI MPSSE | Adaptador Python | FT232H/FT2232H e outros modelos específicos; não significa que qualquer FT232R faça I²C/SPI. O projeto declara Windows não oficialmente suportado/testado e requer libusb apropriado |

Para capturar a comunicação física entre dois equipamentos, usar a ligação de
escuta apropriada ao barramento. UART TTL e RS232 têm interfaces elétricas
diferentes. Um monitor de COM, uma ponte COM e um analisador lógico captam em
pontos diferentes: convém identificar esse ponto em cada registo.

## Outros protocolos e instrumentos

| Projeto | Utilidade | Integração proposta | Requisitos |
|---|---|---|---|
| [PyModbus](https://github.com/pymodbus-dev/pymodbus) | Modbus RTU/ASCII/TCP: cliente, servidor/simulador e interpretação de registos | Adaptador MCP Python | Interface RS485/RS232 adequada ao dispositivo ou ligação de rede. É implementação ativa do protocolo; não é, por si só, um sniffer passivo |
| [python-can](https://github.com/hardbyte/python-can) + [cantools](https://github.com/cantools/cantools) | Capturar/emitir CAN através de interfaces suportadas e descodificar dados com DBC/ARXML | Adaptador Python com sessões e logs | Adaptador CAN e backend compatíveis. cantools interpreta bases de descrição existentes; não descobre automaticamente o significado de um protocolo proprietário |
| [PyVISA](https://github.com/pyvisa/pyvisa) + [PyVISA-py](https://github.com/pyvisa/pyvisa-py) | Controlar instrumentos de medida por USB/LAN/RS232/GPIB; automatizar aquisição de formas de onda e medições | Adaptador MCP com comandos próprios do modelo do instrumento | Backend VISA/USB compatível. O suporte ao transporte não torna universais os comandos SCPI; identificar a marca/modelo do osciloscópio |
| [USBPcap](https://github.com/desowin/usbpcap) + [Wireshark](https://github.com/wireshark/wireshark) | Capturar USB no Windows e analisar/exportar transações | Captura USBPcap + análise TShark/PCAP | Precisa de driver de captura. Observa o USB do PC; não equivale à captura elétrica de RS232/I²C/SPI do outro lado do adaptador |

## Memórias e firmware

| Projeto | Utilidade | Integração proposta | Requisitos/limites |
|---|---|---|---|
| [flashrom](https://github.com/flashrom/flashrom) | Identificar, ler, verificar e programar chips flash, incluindo através de CH341A suportado | Adaptador CLI; dumps e comparação de leituras | Confirmar o chip e o programador/driver/build Windows. O driver CH341A SPI existe no código do projeto; isso não prova compatibilidade com qualquer placa/clip/memória |
| [OpenOCD](https://github.com/openocd-org/openocd) | Depuração JTAG/SWD, memória, breakpoints e programação de alvos suportados | CLI e interfaces Tcl/GDB | Sonda e alvo suportados, com a configuração correta. A documentação inclui instalação Windows via MSYS2 |
| [ImHex](https://github.com/WerWolv/ImHex) | Inspeção hexadecimal, padrões de estruturas, comparação e análise de dumps | Aplicação gráfica; avaliar scripting/CLI para operações específicas | Windows suportado. Não foi confirmado um servidor MCP oficial neste repositório |
| [Binwalk v3](https://github.com/ReFirmLabs/binwalk) | Identificar e extrair conteúdo de firmware e analisar entropia | Adaptador CLI, preferencialmente em ambiente Docker/Linux | README recomenda Docker para todas as dependências; no Windows, validar Docker/WSL. Entropia isolada não demonstra encriptação |
| [Ghidra](https://github.com/NationalSecurityAgency/ghidra) | Desmontagem/decompilação e análise de firmware/binários | Complementar o REA já instalado com um motor compatível | Confirmar a combinação versão Ghidra/JDK/REA e as limitações do provider Windows, antes de anunciar análise nativa completa |

## Expansões com hardware específico

- [Glasgow Interface Explorer](https://github.com/GlasgowEmbedded/glasgow):
  plataforma de interfaces baseada em FPGA; requer placa Glasgow. O equipamento
  confirmado pelo utilizador não identifica esta placa especificamente.
- [Packetry](https://github.com/greatscottgadgets/packetry): análise de USB 2.0
  com Cynthion. Não equivale ao USBPcap; depende do hardware Cynthion para
  aquisição física e de um build adequado ao sistema.
- [rtl_433](https://github.com/merbanan/rtl_433): descodificação/análise de
  transmissões ISM, com recetor SDR compatível ou gravações. Acrescenta RF ao
  conjunto, caso esse seja também um objetivo.

## Candidatos que exigem avaliação separada

- [Lemon Serial Monitor](https://github.com/qingningmneg/LemonSerialMonitor):
  particularmente interessante por ter CLI e MCP de captura COM sem ocupar a
  porta na aplicação. Contudo, o README atual da versão 0.1.1 declara driver
  assinado com certificado local de testes, sem assinatura Microsoft de
  produção. Pode ativar TESTSIGNING; o instalador pára com Secure Boot ativo.
  Esta condição impede tratá-lo como integração Windows normal pronta a usar.
  Fonte: [README inglês](https://github.com/qingningmneg/LemonSerialMonitor/blob/main/README.en.md).
- [URH](https://github.com/jopohl/urh): útil para investigação de protocolos RF,
  mas o repositório está arquivado na consulta de hoje. Não é prioridade para
  uma expansão que deva receber manutenção.
- [ENLYZE PortSniffer](https://github.com/enlyze/PortSniffer): driver/CLI COM
  com interface pública e licença MIT; a documentação de build refere WDK
  7.1.0. Assinatura e compatibilidade Windows atuais precisam de validação.

## Proposta para a app

1. **Imagem:** ImageMagick + rembg; acrescentar transporte de previews para o
   modelo e depois GIMP MCP.
2. **Aquisição:** pySerial + sigrok-cli/PulseView; guardar dados brutos,
   configuração, timestamps e descodificação na pasta do projeto/conversa.
3. **Bancada:** Bus Pirate + PyVISA, com perfis por modelo de equipamento.
4. **Memórias e debug:** flashrom + OpenOCD + ImHex/Ghidra.
5. **Protocolos adicionais:** Modbus, CAN e USB; Binwalk para os dumps de firmware.

As operações propostas para os adaptadores incluem enumerar equipamentos,
iniciar/parar captura, consultar estado, descodificar ficheiros e exportar
resultados. Transmissão/escrita/programação são operações separadas da leitura
ou captura e usam as aprovações da ferramenta configuradas na app.

Estado verificado do código atual: `mcp_bridge.py` substitui blocos MCP de
imagem/áudio por uma nota. O preview de um editor não chega hoje ao modelo por
essa via. Isso precisa de suporte antes de afirmar que o agente verifica as
próprias edições ou screenshots de instrumentos.

Os projetos aqui listados ainda precisam de instalação, adaptador quando não
têm MCP e testes com o hardware concreto. A pesquisa não alterou drivers,
firmware nem a configuração das ferramentas existentes.
