"""Ponte ``Api``: provedores, modelos e seleção do modelo ativo por tipo.

Classe-base de ``api.Api`` (extraída de ``api.py`` sem alterações ao código).
Os métodos sem ``_`` inicial são chamados pela interface através da ponte do
pywebview. A chave de API nunca é devolvida: as respostas passam por
``get_state``, que só expõe ``has_key``.

Depende de ``self.get_state`` (método de ``api.Api``).
"""

from __future__ import annotations

import config
import providers
import rig
from agent_runtime import PROFILES
from api_helpers import (
    MODEL_SLOTS,
    MODEL_TYPES,
    _TYPE_LABEL,
    _err,
    _find_model,
    _find_provider,
    _fmt_exc,
    _ok,
    _slot_type,
    _slug,
    _unique_id,
)


CATALOG_VERSION = 2


class ProvidersApi:
    # ------------------------------------------------------------------ #
    # Seleção de modelos por tipo
    # ------------------------------------------------------------------ #
    def set_model(self, slot: str, provider_id: str, model_id: str) -> dict:
        try:
            if slot not in MODEL_SLOTS:
                return _err(f"Tipo de modelo inválido: {slot}")
            cfg = config.load_config()
            if provider_id and model_id:
                provider = _find_provider(cfg, provider_id)
                model = (_find_model(provider, model_id, _slot_type(slot)) or _find_model(provider, model_id)) if provider else None
                if provider is None or model is None:
                    return _err("Modelo escolhido não encontrado.")
                if model.get("type") != _slot_type(slot):
                    return _err(
                        f"O modelo '{model_id}' é do tipo "
                        f"{_TYPE_LABEL.get(model.get('type'), model.get('type'))}, "
                        f"não {_TYPE_LABEL.get(slot, slot)}."
                    )
                cfg[slot] = {"provider_id": provider_id, "model_id": model_id}
            else:
                cfg[slot] = {}
            config.save_config(cfg)
            return self.get_state()
        except Exception as exc:  # noqa: BLE001
            return _err(_fmt_exc(exc))

    # ------------------------------------------------------------------ #
    # CRUD de provedores (global)
    # ------------------------------------------------------------------ #
    def add_provider(self, data: dict) -> dict:
        try:
            cfg = config.load_config()
            name = (data.get("name") or "").strip()
            kind = (data.get("kind") or "").strip()
            if not name:
                return _err("O provedor precisa de um nome.")
            if not kind:
                return _err("Escolhe o tipo (kind) do provedor.")
            if kind not in providers.available_kinds():
                return _err(f"Tipo de provedor desconhecido: '{kind}'. Disponíveis: {', '.join(providers.available_kinds())}.")
            provider = {
                "id": _unique_id(_slug(name), cfg),
                "name": name,
                "kind": kind,
                "base_url": (data.get("base_url") or "").strip(),
                "api_key": (data.get("api_key") or "").strip(),
                "models": [],
            }
            cfg.setdefault("providers", []).append(provider)
            config.save_config(cfg)
            return self.get_state()
        except Exception as exc:  # noqa: BLE001
            return _err(_fmt_exc(exc))

    def discover_provider_models(self, provider_id: str) -> dict:
        try:
            provider=_find_provider(config.load_config(),provider_id)
            if not provider:return _err('Provedor não encontrado.')
            return _ok(**providers.list_models(provider))
        except Exception as exc:
            text=str(exc)
            if 'provider' in locals() and provider and provider.get('api_key'):text=text.replace(provider['api_key'],'[chave oculta]')
            return _err(text)

    def sync_provider_models(self, provider_id: str, force: bool = False) -> dict:
        try:
            import time
            from providers.catalog import merge
            cfg = config.load_config()
            provider = _find_provider(cfg, provider_id)
            if not provider:
                return _err('Provedor não encontrado.')
            # CATALOG_VERSION sobe quando a app passa a guardar mais coisas do catálogo (2 = vozes dos modelos de áudio):
            # a primeira sincronização depois de atualizar a app não espera pelas 24 horas.
            if not force and provider.get('catalog_version') == CATALOG_VERSION and time.time() - provider.get('catalog_updated_at', 0) < 86400:
                return self.get_state()
            identity = tuple(provider.get(k) for k in ('kind', 'base_url', 'api_key'))
            result = providers.list_models(provider)
            if result.get('truncated'):
                return _err('O provedor devolveu uma lista parcial; o catálogo anterior foi preservado.')
            # Network access must not overwrite edits made while waiting for the provider.
            cfg = config.load_config()
            provider = _find_provider(cfg, provider_id)
            if not provider or identity != tuple(provider.get(k) for k in ('kind', 'base_url', 'api_key')):
                return _err('O provedor mudou durante a consulta. Atualiza novamente.')
            added = merge(provider, result['models'])
            provider['catalog_updated_at'] = time.time()
            provider['catalog_version'] = CATALOG_VERSION
            config.save_config(cfg)
            state = self.get_state()
            state['catalog_added'] = added
            return state
        except Exception as exc:
            text = str(exc)
            if 'provider' in locals() and provider and provider.get('api_key'):
                text = text.replace(provider['api_key'], '[chave oculta]')
            return _err(text)

    def set_agent_model(self, profile: str, provider_id: str = '', model_id: str = '') -> dict:
        try:
            if profile not in (*PROFILES,'explore'):return _err('Perfil inválido.')
            cfg=config.load_config()
            if provider_id or model_id:
                provider=_find_provider(cfg,provider_id);model=_find_model(provider,model_id,'chat') if provider else None
                if not model or model.get('type')!='chat' or not providers.family_caps(provider['kind'])['chat']:return _err('Seleciona um modelo de chat válido.')
                value=dict(provider_id=provider_id,model_id=model_id)
            else:value={}
            cfg.setdefault('preferences',{}).setdefault('agent_models',{})[profile]=value
            config.save_config(cfg);return self.get_state()
        except Exception as exc:return _err(str(exc))

    def set_rig(self, data: dict) -> dict:
        """Escolhe onde correm os modelos de conversa — provedores online ou a rig do utilizador — e guarda as
        definições da rig (endereço, chave, esforço de raciocínio e voz). ``enabled`` verdadeiro = modo local.

        Ao passar a local, pergunta à rig que modelo tem; se ela não responder, as definições ficam guardadas
        mas continua-se em modo online e o motivo vem em ``rig_error``. Uma chave vazia mantém a que já estava.
        """
        try:
            if not isinstance(data, dict):
                return _err('Definições da rig inválidas.')
            cfg = config.load_config()
            provider = rig.find(cfg)
            try:
                address = rig.origin(data['address'] if 'address' in data else (provider or {}).get('base_url', ''))
            except rig.RigError as exc:
                return _err(str(exc))
            effort = data.get('effort') or (provider or {}).get('effort') or 'leve'
            if effort not in rig.EFFORTS:
                return _err('Esforço de raciocínio inválido.')
            wanted = bool(data.get('enabled'))
            if wanted and not address:
                return _err('Escreve o endereço da rig, por exemplo http://192.168.0.10:8080.')
            new_key = data.get('api_key')
            key = new_key.strip() if isinstance(new_key, str) and new_key.strip() else (provider or {}).get('api_key', '')
            was = bool((provider or {}).get('enabled'))
            same = bool(provider) and provider.get('base_url') == (address + '/v1' if address else '') and provider.get('api_key', '') == key
            if provider is None:
                provider = dict(id=_unique_id(_slug(rig.NAME), cfg), name=rig.NAME, kind='openai-compatible', models=[], rig=True)
                cfg.setdefault('providers', []).append(provider)
            provider.update(name=rig.NAME, base_url=address + '/v1' if address else '', api_key=key, effort=effort, enabled=False)
            note = ''
            if wanted:
                try:
                    found = rig.probe_all(address, key)
                except rig.RigError as exc:
                    note = str(exc)
                    # Já em modo local e sem mexer no endereço nem na chave (ex.: mudar o «Pensamento»): uma falha passageira
                    # da rig não tira a app do modo local nem apaga o modelo escolhido; fica com os modelos que já conhecia.
                    if was and same and provider.get('models'):
                        provider['enabled'] = True
                else:
                    provider['gateway'] = bool(found[0].get('gateway'))  # porta única (porteiro): a voz também passa por ela
                    provider['models'] = [dict(id=item['model'], name=item['model'], type='chat', categories=['code'], base_url=item['base'] + '/v1',
                                               defaults={'context_window': item['context']} if item['context'] else {},
                                               **({'accepts_images': item['vision']} if 'vision' in item else {})) for item in found]
                    provider['enabled'] = True
            preferences = cfg.setdefault('preferences', {})
            if provider['enabled']:
                # Modo local: a conversa e os subagentes passam todos para a rig. O que estava escolhido nos
                # provedores online fica guardado para voltar tal e qual. Imagem, vídeo e áudio não mudam.
                if not was:
                    provider['previous'] = dict(chat=cfg.get('chat') or {}, agent_models=preferences.get('agent_models') or {})
                current = cfg.get('chat') or {}
                keep = current.get('provider_id') == provider['id'] and any(m['id'] == current.get('model_id') for m in provider['models'])
                if not keep:  # mantém o modelo da rig que já estava escolhido; senão, o primeiro
                    cfg['chat'] = {'provider_id': provider['id'], 'model_id': provider['models'][0]['id']}
                preferences['agent_models'] = {}
            else:  # modo online: nada pode ficar a apontar para a rig, e repõe-se o que estava antes
                for slot in MODEL_SLOTS:
                    if (cfg.get(slot) or {}).get('provider_id') == provider['id']:
                        cfg[slot] = {}
                roles = preferences.setdefault('agent_models', {})
                for role in list(roles):
                    if roles[role].get('provider_id') == provider['id']:
                        roles.pop(role)
                previous = provider.pop('previous', None) or {}

                def valid(choice):
                    owner = _find_provider(cfg, (choice or {}).get('provider_id', ''))
                    return bool(owner and not owner.get('rig') and _find_model(owner, choice.get('model_id', ''), 'chat'))
                if was and not (cfg.get('chat') or {}).get('model_id') and valid(previous.get('chat')):
                    cfg['chat'] = previous['chat']
                if was and not roles:
                    roles.update({role: choice for role, choice in (previous.get('agent_models') or {}).items() if valid(choice)})
            preferences['voice_server'] = rig.whisper_address(address, provider.get('gateway')) if provider['enabled'] and data.get('whisper') else ''
            config.save_config(cfg)
            state = self.get_state()
            if note:
                state['rig_error'] = note
            return state
        except Exception as exc:  # noqa: BLE001
            text = _fmt_exc(exc)
            if 'key' in locals() and key:
                text = text.replace(key, '[chave oculta]')
            return _err(text)

    def update_provider(self, provider_id: str, data: dict) -> dict:
        try:
            cfg = config.load_config()
            provider = _find_provider(cfg, provider_id)
            if provider is None:
                return _err(f"Provedor '{provider_id}' não encontrado.")
            if "name" in data and (data.get("name") or "").strip():
                provider["name"] = data["name"].strip()
            if "kind" in data and (data.get("kind") or "").strip():
                kind = data["kind"].strip()
                if kind not in providers.available_kinds():
                    return _err(f"Tipo de provedor desconhecido: '{kind}'.")
                provider["kind"] = kind
            if "base_url" in data:
                provider["base_url"] = (data.get("base_url") or "").strip()
            new_key = data.get("api_key")
            if new_key is not None and new_key.strip():
                provider["api_key"] = new_key.strip()
            config.save_config(cfg)
            return self.get_state()
        except Exception as exc:  # noqa: BLE001
            return _err(_fmt_exc(exc))

    def remove_provider(self, provider_id: str) -> dict:
        try:
            cfg = config.load_config()
            before = len(cfg.get("providers", []))
            cfg["providers"] = [p for p in cfg.get("providers", []) if p.get("id") != provider_id]
            if len(cfg["providers"]) == before:
                return _err(f"Provedor '{provider_id}' não encontrado.")
            for slot in MODEL_SLOTS:
                if (cfg.get(slot) or {}).get("provider_id") == provider_id:
                    cfg[slot] = {}
            roles=cfg.setdefault('preferences',{}).setdefault('agent_models',{})
            for role in list(roles):
                if roles[role].get('provider_id')==provider_id:roles.pop(role)
            config.save_config(cfg)
            return self.get_state()
        except Exception as exc:  # noqa: BLE001
            return _err(_fmt_exc(exc))

    # ------------------------------------------------------------------ #
    # CRUD de modelos (global)
    # ------------------------------------------------------------------ #
    def add_model(self, provider_id: str, model: dict) -> dict:
        try:
            cfg = config.load_config()
            provider = _find_provider(cfg, provider_id)
            if provider is None:
                return _err(f"Provedor '{provider_id}' não encontrado.")
            model_id = (model.get("id") or "").strip()
            if not model_id:
                return _err("O modelo precisa de um ID.")
            mtype = (model.get("type") or "image").strip()
            if mtype not in MODEL_TYPES:
                return _err(f"Tipo de modelo inválido: '{mtype}'.")
            if not providers.family_caps(provider['kind']).get(mtype):return _err('Este adaptador não suporta '+mtype+'.')

            models = provider.setdefault("models", [])
            if any(m.get("id") == model_id and m.get("type") == mtype for m in models):
                return _err(f"O modelo '{model_id}' ({mtype}) já existe neste provedor.")

            models.append(
                {
                    "id": model_id,
                    "name": (model.get("name") or model_id).strip(),
                    "type": mtype,
                    "defaults": model.get("defaults") or {},
                }
            )
            if not (cfg.get(mtype) or {}).get("model_id"):
                cfg[mtype] = {"provider_id": provider_id, "model_id": model_id}
            config.save_config(cfg)
            return self.get_state()
        except Exception as exc:  # noqa: BLE001
            return _err(_fmt_exc(exc))

    def set_model_voice(self, provider_id: str, model_id: str, voice: str = '') -> dict:
        """Escolhe a voz de um modelo de áudio (fica nos ``defaults`` do modelo). Vazia = a primeira do modelo."""
        try:
            cfg = config.load_config()
            provider = _find_provider(cfg, provider_id)
            model = _find_model(provider, model_id, 'audio') if provider else None
            if model is None:
                return _err('Modelo de áudio não encontrado.')
            voice = voice.strip() if isinstance(voice, str) else ''
            if len(voice) > 80:
                return _err('Nome de voz demasiado comprido.')
            known = [v for v in (model.get('voices') or []) if isinstance(v, str)]
            if voice and known:
                match = next((v for v in known if v.lower() == voice.lower()), None)
                if match is None:
                    return _err('Este modelo não tem a voz «%s».' % voice)
                voice = match
            defaults = dict(model.get('defaults') or {})
            defaults.pop('voice', None)
            if voice:
                defaults['voice'] = voice
            model['defaults'] = defaults
            config.save_config(cfg)
            return self.get_state()
        except Exception as exc:  # noqa: BLE001
            return _err(_fmt_exc(exc))

    def remove_model(self, provider_id: str, model_id: str) -> dict:
        try:
            cfg = config.load_config()
            provider = _find_provider(cfg, provider_id)
            if provider is None:
                return _err(f"Provedor '{provider_id}' não encontrado.")
            before = len(provider.get("models", []))
            provider["models"] = [m for m in provider.get("models", []) if m.get("id") != model_id]
            if len(provider["models"]) == before:
                return _err(f"Modelo '{model_id}' não encontrado.")
            for slot in MODEL_SLOTS:
                sel = cfg.get(slot) or {}
                if sel.get("provider_id") == provider_id and sel.get("model_id") == model_id:
                    cfg[slot] = {}
            roles=cfg.setdefault('preferences',{}).setdefault('agent_models',{})
            for role in list(roles):
                if roles[role].get('provider_id')==provider_id and roles[role].get('model_id')==model_id:roles.pop(role)
            config.save_config(cfg)
            return self.get_state()
        except Exception as exc:  # noqa: BLE001
            return _err(_fmt_exc(exc))
