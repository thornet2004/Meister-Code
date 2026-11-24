# Componentes opcionais da bancada

As aplicações, bibliotecas e fontes em `Ferramentas` são componentes separados;
os autores e as respetivas licenças originais permanecem nessas pastas.
O executável da Studio contém os adaptadores e a interface, não incorpora estes
editores, drivers, firmware ou modelos no seu binário.

`Ferramentas/<nome>/instalacao.json` regista versões, origens e hashes dos
downloads. `fonte.json` identifica o commit das fontes. O inventário detalhado
está em `Ferramentas/INVENTARIO.md`. As dependências Python e respetivas licenças
estão em `Ferramentas/_Runtime/site-packages/*dist-info`; as versões efetivamente
instaladas estão em `_Runtime/installed-packages.json`.

As fontes de ImageMagick MCP (MIT), GIMP MCP (GPL-3.0), Binwalk (MIT), Glasgow
(0BSD/Apache-2.0), URH (GPL-3.0), Lemon e PortSniffer preservam os ficheiros de
licença dos repositórios originais. As distribuições nativas incluem os seus
avisos de copyright/licenças. Consulte esses textos antes de redistribuir.

REA, ClassRevive e Android Reverse Engineering mantêm as licenças já existentes
nas suas próprias pastas. A presença de um adaptador não altera essas licenças.
