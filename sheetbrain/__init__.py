# SheetBrain — microsoft/SheetBrain, licença MIT (ver sheetbrain/LICENSE).
# Cópia incorporada (vendored) na MeisterCode, com pequenos ajustes marcados com
# "MeisterCode:" no código: imports absolutos passaram ao prefixo "sheetbrain.",
# o matplotlib ficou opcional (import preguiçoso) e o tiktoken foi removido
# (contagem de tokens por heurística, para a app funcionar offline e sem inchar).
# Fonte: https://github.com/microsoft/SheetBrain
#
# Import preguiçoso: "import sheetbrain" não puxa logo o openai/openpyxl; só quando
# se acede a SheetBrain/Config é que os módulos pesados são carregados.

__all__ = ["SheetBrain", "Config"]


def __getattr__(name):
    if name == "SheetBrain":
        from sheetbrain.core.agent import SheetBrain
        return SheetBrain
    if name == "Config":
        from sheetbrain.config.settings import Config
        return Config
    raise AttributeError("module 'sheetbrain' has no attribute " + repr(name))
