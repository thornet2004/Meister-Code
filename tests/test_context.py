import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import api
import config


def _messages(count):
    return [
        {
            "role": "user" if index % 2 == 0 else "assistant",
            "text": f"mensagem {index}",
            "media": [],
            "files": [],
            "steps": [],
            "created_at": "2026-01-01T00:00:00",
        }
        for index in range(count)
    ]


class ContextTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.root = Path(self.temp.name).resolve()
        self.settings = self.root / "settings"
        self.app_root = self.root / "app"
        self.settings.mkdir()
        self.app_root.mkdir()
        self.patches = [
            patch("config.config_dir", return_value=self.settings),
            patch("config.application_root", return_value=self.app_root),
        ]
        for item in self.patches:
            item.start()
        config.save_config(config.default_config())
        self.app = api.Api()

    def tearDown(self):
        self.app._mcp.close()
        for item in reversed(self.patches):
            item.stop()
        self.temp.cleanup()

    def _save(self, messages):
        state = self.app.create_conversation("Teste")
        self.assertTrue(state["ok"], state)
        cfg = config.load_config()
        meta_dir, _output = config.resolve_context(cfg)
        api._save_conversation(messages, meta_dir)
        return meta_dir

    def _chat_model(self, window=32000):
        cfg = config.load_config()
        cfg["providers"] = [{
            "id": "p", "name": "P", "kind": "openrouter",
            "models": [{"id": "m", "name": "M", "type": "chat", "defaults": {"context_window": window}}],
        }]
        cfg["chat"] = {"provider_id": "p", "model_id": "m"}
        config.save_config(cfg)

    def test_context_usage_and_limit(self):
        self._chat_model(32000)
        self._save(_messages(5))
        usage = self.app.get_context_usage()
        self.assertTrue(usage["ok"], usage)
        self.assertEqual(usage["limit"], 32000)
        self.assertEqual(usage["limit_source"], "model")
        self.assertGreater(usage["used"], 0)
        self.assertGreater(usage["percent"], 0)
        self.assertIn("mensagens", usage["parts"])
        self.assertTrue(usage["series"])
        self.assertEqual(usage["total_messages"], 5)

        changed = self.app.set_context_window(64000)
        self.assertTrue(changed["ok"], changed)
        model = config.load_config()["providers"][0]["models"][0]
        self.assertEqual(model["defaults"]["context_window"], 64000)
        self.assertEqual(self.app.get_context_usage()["limit"], 64000)

    def test_zero_disables_context_limit_and_survives_reload(self):
        self._chat_model()
        self._save(_messages(5))
        self.assertTrue(self.app.set_context_window("0")["ok"])
        self.assertEqual(config.load_config()["providers"][0]["models"][0]["defaults"]["context_window"], 0)
        usage = self.app.get_context_usage()
        self.assertEqual(usage["limit"], 0)
        self.assertEqual(usage["percent"], 0)
        self.assertGreater(usage["used"], 0)
        self.assertFalse(self.app.set_context_window(-1)["ok"])
        self.assertFalse(self.app.set_context_window(999)["ok"])
        self.assertTrue(self.app.set_context_window(32000)["ok"])
        self.assertEqual(self.app.get_context_usage()["limit"], 32000)

    def test_set_context_window_requires_chat_model(self):
        result = self.app.set_context_window(32000)
        self.assertFalse(result["ok"])
        self.assertIn("modelo de chat", result["error"])
        self.assertFalse(self.app.set_context_window("nope")["ok"])
    def test_config_access_error_does_not_reset_saved_configuration(self):
        self._chat_model();path=config.config_path();before=path.read_bytes()
        with patch('config.read_json',side_effect=PermissionError('busy')):
            with self.assertRaises(PermissionError):config.load_config()
        self.assertEqual(path.read_bytes(),before);self.assertFalse(path.with_suffix('.json.bak').exists())

    def test_compact_uses_local_summary_without_chat_model(self):
        conv = [{"role": "user", "text": "primeira decisão: usar Python"}, *[
            {"role": "user" if i % 2 == 0 else "assistant", "text": f"mensagem {i}"}
            for i in range(19)
        ]]
        meta_dir = self._save(conv)
        result = self.app.compact_context()
        self.assertTrue(result["ok"], result)
        self.assertFalse(result["used_model"])
        self.assertEqual(result["kept"], 12)
        self.assertEqual(result["compacted"], len(conv) - 12)
        compacted = api._load_conversation(meta_dir)
        self.assertEqual(len(compacted), 13)
        self.assertEqual(compacted[0]["role"], "summary")
        self.assertIn("Resumo compactado", compacted[0]["text"])
        self.assertEqual(compacted[1]["text"], conv[-12]["text"])
        self.assertTrue((Path(meta_dir) / "conversation.before-compact.json").exists())
        usage = self.app.get_context_usage()
        self.assertTrue(usage["compacted"])

    def test_registered_decisions_and_tasks_survive_compaction_and_are_injected(self):
        meta=self._save(_messages(22));decision=self.app.update_context_record('decision','Usar PostgreSQL no backend.');self.assertTrue(decision['ok'],decision)
        task=self.app.update_context_record('task','Migrar o schema.');key=task['continuity']['tasks'][0]['id'];self.app.update_context_record('task','Migrar o schema.',key,'done')
        self.assertTrue(self.app.compact_context()['ok']);cfg=config.load_config();ctx=self.app._agent_context(cfg);self.app._attach_project_context(ctx,meta,'schema')
        messages=api._build_model_messages(api._load_conversation(meta),ctx,[]);payload='\n'.join(m.get('content','') for m in messages if isinstance(m.get('content'),str))
        self.assertIn('PostgreSQL',payload);self.assertIn('Migrar o schema.',payload);self.assertIn('"state": "done"',payload)
        self.assertEqual(self.app.get_project_context()['continuity']['tasks'][0]['state'],'done')
    def test_compact_uses_model_summary_and_instruction(self):
        self._chat_model()
        conv = [{"role": "user" if i % 2 == 0 else "assistant", "text": f"mensagem {i}"} for i in range(20)]
        _meta = self._save(conv)
        calls = []

        def adapter(provider, model, messages, tools, params):
            calls.append(messages)
            return {"content": "Resumo gerado pelo modelo.", "tool_calls": []}

        with patch("providers.get_chat_adapter", return_value=adapter):
            result = self.app.compact_context("decisões sobre a base de dados")
        self.assertTrue(result["ok"], result)
        self.assertTrue(result["used_model"])
        self.assertTrue(calls)
        self.assertTrue(any(
            "Foco pedido: decisões sobre a base de dados" in (message.get("content") or "")
            for message in calls[0] if message.get("role") == "system"
        ))
        compacted = api._load_conversation(_meta)
        self.assertIn("Resumo gerado pelo modelo.", compacted[0]["text"])

    def test_compact_command_is_intercepted(self):
        conv = [{"role": "user" if i % 2 == 0 else "assistant", "text": f"mensagem {i}"} for i in range(20)]
        _meta = self._save(conv)
        result = self.app.chat("/compact")
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["kept"], 12)
        compacted = api._load_conversation(_meta)
        self.assertEqual(compacted[0]["role"], "summary")

    def test_restore_compaction(self):
        conv = [{"role": "user" if i % 2 == 0 else "assistant", "text": f"mensagem {i}"} for i in range(20)]
        _meta = self._save(conv)
        self.assertTrue(self.app.compact_context()["ok"])
        restored = self.app.restore_compaction()
        self.assertTrue(restored["ok"], restored)
        self.assertEqual(api._load_conversation(_meta), conv)
        self.assertFalse(self.app.restore_compaction()["ok"])

    def test_search_messages_across_contexts(self):
        self._save(_messages(3))
        state = self.app.create_conversation("Segunda")
        self.assertTrue(state["ok"], state)
        meta_two, _out = config.resolve_context(config.load_config())
        api._save_conversation([{"role": "user", "text": "segredo sobre a base de dados"}], meta_two)
        result = self.app.search_messages("base de dados")
        self.assertTrue(result["ok"], result)
        self.assertEqual(len(result["results"]), 1)
        self.assertEqual(result["results"][0]["context_name"], "Segunda")
        self.assertIn("base de dados", result["results"][0]["snippet"])
        self.assertFalse(self.app.search_messages("x")["results"])

    def test_summary_role_is_sent_as_system(self):
        messages = api._build_model_messages([{"role": "summary", "text": "Resumo X"}], None, [])
        self.assertTrue(any(m["role"] == "system" and "Resumo X" in m["content"] for m in messages))

    def test_text_only_model_gets_no_images(self):
        import chat_messages
        provider = dict(catalog=[dict(id='texto', input_modalities=['text']), dict(id='visao', input_modalities=['text', 'image']), dict(id='incerto', input_modalities=[])])
        self.assertFalse(chat_messages._accepts_images(provider, dict(id='texto')))
        self.assertTrue(chat_messages._accepts_images(provider, dict(id='visao')))
        self.assertTrue(chat_messages._accepts_images(provider, dict(id='incerto')))
        self.assertTrue(chat_messages._accepts_images(dict(), dict(id='fora-do-catalogo')))
        original = [dict(role='system', content='regras'), dict(role='user', content=[dict(type='text', text='Imagens produzidas'), dict(type='image_url', image_url=dict(url='data:image/png;base64,YQ=='))]), dict(role='user', content='continua')]
        clean = chat_messages._without_images(original)
        self.assertEqual([m['role'] for m in clean], ['system', 'user', 'user'])
        self.assertEqual(clean[1]['content'], 'Imagens produzidas\n' + chat_messages.IMAGE_NOTE)
        self.assertNotIn('image_url', str(clean))
        self.assertIsInstance(original[1]['content'], list)

    def test_new_install_agent_can_write_and_off_is_explained(self):
        self.assertEqual(config.default_config()['preferences']['agent'], dict(enabled=True, scope='computer', approval='writes', confirm_dangerous=True))
        cfg = config.default_config()
        ctx = self.app._agent_context(cfg)
        self.assertTrue(ctx['on']);self.assertEqual(ctx['off_reason'], '')
        cfg['preferences']['agent']['enabled'] = False
        ctx = self.app._agent_context(cfg);self.assertEqual(ctx['off_reason'], 'disabled')
        system = api._build_model_messages([dict(role='user', text='grava')], ctx, [])[0]['content']
        self.assertIn('Configurações → Agente', system);self.assertIn('desligado', system)
        cfg['preferences']['agent'].update(enabled=True, scope='project');cfg['projects'] = [];cfg['active_project_id'] = ''
        ctx = self.app._agent_context(cfg);self.assertFalse(ctx['on']);self.assertEqual(ctx['off_reason'], 'no_project')
        self.assertIn('todo o PC', api._build_model_messages([dict(role='user', text='grava')], ctx, [])[0]['content'])

    def test_model_is_told_the_real_user_folders_and_must_not_claim_writes(self):
        import chat_messages
        folders = chat_messages._user_folders()
        self.assertEqual(list(folders), ['Ambiente de trabalho', 'Documentos', 'Transferências'])
        self.assertTrue(all(Path(value).is_absolute() for value in folders.values()), folders)
        with patch.object(chat_messages, '_user_folders', return_value={'Ambiente de trabalho': r'C:\Users\x\OneDrive\Desktop'}):
            system = api._build_model_messages([dict(role='user', text='grava')], dict(on=True, scope='computer', base=str(Path.cwd()), profile='build'), [])[0]['content']
        self.assertIn(r'Ambiente de trabalho = C:\Users\x\OneDrive\Desktop', system)
        self.assertIn('caminho completo que a ferramenta devolveu', system)
        off = api._build_model_messages([dict(role='user', text='grava')], dict(on=False, off_reason='disabled'), [])[0]['content']
        self.assertIn('Nunca digas que gravaste', off)

    def test_personality_changes_only_the_tone_of_the_prompt(self):
        import chat_messages
        cfg = config.load_config()
        plain = api._build_model_messages([dict(role='user', text='olá')], self.app._agent_context(cfg), [])[0]['content']
        self.assertNotIn('Personalidade escolhida', plain, 'a neutra não acrescenta nada')
        self.assertFalse(self.app.set_preference('personality', 'malcriado')['ok'])
        for key in ('sociavel', 'sarcastico', 'bruto', 'profissional'):
            self.assertEqual(self.app.set_preference('personality', key)['preferences']['personality'], key)
            system = api._build_model_messages([dict(role='user', text='olá')], self.app._agent_context(config.load_config()), [])[0]['content']
            self.assertIn(chat_messages.PERSONALITIES[key][1], system)
            self.assertIn('nunca inventes factos', system, 'a personagem não dispensa o rigor')
        self.app.set_preference('voice_reply', True)
        spoken = api._build_model_messages([dict(role='user', text='olá')], self.app._agent_context(config.load_config()), [])[0]['content']
        self.assertIn('lida em voz alta', spoken);self.assertIn('És formal e sóbrio', spoken, 'vale também na conversa por voz')
        self.app.set_preference('voice_reply', False)
        self.assertEqual(self.app.set_preference('personality', 'neutra')['preferences']['personality'], 'neutra')

    def test_app_notices_are_not_sent_to_the_model_as_its_own_words(self):
        from api_helpers import _error_turn
        conv = [dict(role='user', text='estás online?'), _error_turn('Não há modelo de chat escolhido. Nas listas por baixo da caixa escolhe o tipo Chat.'),
                dict(role='user', text='e agora?'), dict(role='assistant', text='⚠️ Erro HTTP 503 de http://rig:8081', media=[], files=[], steps=[]),
                dict(role='assistant', text='⚠️ Cuidado: este comando apaga a pasta.', steps=[dict(tool='powershell', result='ok')]),
                dict(role='assistant', text='Estou aqui.'), dict(role='user', text='estás online?')]
        sent = api._build_model_messages(conv, self.app._agent_context(config.load_config()), [])
        texts = [str(m['content']) for m in sent if m['role'] != 'system']
        self.assertFalse(any('Não há modelo de chat' in text or 'Erro HTTP 503' in text for text in texts), 'os avisos da app ficam de fora')
        self.assertTrue(any('Cuidado: este comando' in text for text in texts), 'uma resposta do modelo que comece por ⚠️ e tenha trabalho feito fica')
        self.assertEqual([m['role'] for m in sent if m['role'] != 'system'][-3:], ['assistant', 'assistant', 'user'])
        self.assertEqual(sum('estás online?' in text or 'e agora?' in text for text in texts), 3, 'as mensagens do utilizador não se perdem')

    def test_picker_type_is_remembered(self):
        self.assertFalse(self.app.set_preference('picker_type', 'inventado')['ok'])
        self.assertEqual(self.app.set_preference('picker_type', 'image')['preferences']['picker_type'], 'image')
        self.assertEqual(self.app.get_state()['preferences']['picker_type'], 'image')

    def test_agent_name_for_voice_is_trimmed_and_limited(self):
        """Nome por que o agente responde na conversa por voz (pedido do user, 24/11/2026)."""
        self.assertEqual(self.app.get_state()['preferences']['agent_name'], '', 'por omissão vazio: responde a tudo')
        self.assertEqual(self.app.set_preference('agent_name', '  Zé  ')['preferences']['agent_name'], 'Zé', 'os espaços à volta saem')
        self.assertEqual(self.app.get_state()['preferences']['agent_name'], 'Zé')
        self.assertFalse(self.app.set_preference('agent_name', 'z' * 41)['ok'], 'nome demasiado longo é recusado')
        self.assertFalse(self.app.set_preference('agent_name', 123)['ok'])
        self.assertEqual(self.app.set_preference('agent_name', '')['preferences']['agent_name'], '', 'pode voltar a vazio')

    def test_regenerate_edit_and_branch(self):
        self._chat_model()
        conv = [
            {"role": "user", "text": "pergunta antiga"},
            {"role": "assistant", "text": "resposta antiga"},
            {"role": "user", "text": "pergunta atual"},
            {"role": "assistant", "text": "resposta atual"},
        ]
        _meta = self._save(conv)

        def adapter(provider, model, messages, tools, params):
            return {"content": "resposta nova", "tool_calls": []}

        with patch("providers.get_chat_adapter", return_value=adapter):
            result = self.app.regenerate()
        self.assertTrue(result["ok"], result)
        regenerated = api._load_conversation(_meta)
        self.assertEqual(len(regenerated), 4)
        self.assertEqual(regenerated[-1]["text"], "resposta nova")
        self.assertEqual(regenerated[-2]["text"], "pergunta atual")

        with patch("providers.get_chat_adapter", return_value=adapter):
            result = self.app.edit_resend(0, "pergunta editada")
        self.assertTrue(result["ok"], result)
        edited = api._load_conversation(_meta)
        self.assertEqual(len(edited), 2)
        self.assertEqual(edited[0]["text"], "pergunta editada")
        self.assertEqual(edited[1]["text"], "resposta nova")

        state = self.app.branch_conversation(1)
        self.assertTrue(state["ok"], state)
        branch = next(c for c in state["conversations"] if c["id"] == state["active_conversation_id"])
        branch_meta = Path(branch["path"])
        branched = api._load_conversation(branch_meta)
        self.assertEqual(len(branched), 2)
        self.assertEqual(branched[0]["text"], "pergunta editada")
