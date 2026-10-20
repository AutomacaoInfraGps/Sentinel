import unittest

from sofia import engine


class SofiaEngineTests(unittest.TestCase):
    def setUp(self):
        self._originals = {
            "identificar_regional": engine.identificar_regional,
            "listar_nomes_regionais": engine.listar_nomes_regionais,
            "nome_regional": engine.nome_regional,
            "total_regionais": engine.total_regionais,
            "resumo_links": engine.resumo_links,
            "resumo_servidores": engine.resumo_servidores,
            "resumo_switches": engine.resumo_switches,
            "alertas_switches_ativos": engine.alertas_switches_ativos,
            "consultar_manutencoes_regionais": engine.consultar_manutencoes_regionais,
        }

        engine.identificar_regional = (
            lambda mensagem, allowed_regionals=None:
            "REG_ABC" if "abc" in mensagem else None
        )
        engine.nome_regional = lambda codigo, allowed_regionals=None: {
            "REG_ABC": "REG_ABC"
        }.get(codigo, "Regional")
        engine.total_regionais = lambda allowed_regionals=None: 3
        engine.listar_nomes_regionais = lambda limite=50, allowed_regionals=None: [
            "REG_ABC",
            "REG_BAHIA",
            "REG_CEARA",
        ][:limite]
        engine.resumo_links = lambda codigo=None, allowed_regionals=None: {
            "total": 2,
            "online": 1,
            "offline": 1,
        }
        engine.resumo_servidores = lambda codigo=None, allowed_regionals=None: {
            "total": 4,
            "online": 3,
            "warning": 1,
        }
        engine.resumo_switches = lambda codigo=None, allowed_regionals=None: {
            "total": 5,
            "online": 4,
            "offline": 1,
        }
        engine.alertas_switches_ativos = lambda codigo=None, allowed_regionals=None: [
            {
                "switch": "SWT-ABC-01",
                "regional": "REG_ABC",
                "alerta": "CPU alta",
            }
        ]
        engine.consultar_manutencoes_regionais = lambda allowed_regionals=None: {
            "available": True,
            "total": 1,
            "regionals": [{
                "code": "REG_ABC",
                "name": "REG_ABC",
                "in_maintenance": True,
                "maintenance_windows": [{"name": "MIGRACAO ABC"}],
            }],
        }

    def tearDown(self):
        for name, original in self._originals.items():
            setattr(engine, name, original)

    def perguntar(self, mensagem):
        return engine.processar_mensagem_sofia(usuario="teste", mensagem=mensagem)

    def test_responde_saudacao(self):
        resposta = self.perguntar("oi")
        self.assertIn("SofIA", resposta)

    def test_responde_total_regionais(self):
        resposta = self.perguntar("quantas regionais temos?")
        self.assertIn("3 regionais", resposta)

    def test_lista_regionais_sem_depender_do_historico_do_modelo(self):
        resposta = self.perguntar("Quais são elas?")

        self.assertIn("3 regionais", resposta)
        self.assertIn("- REG_ABC", resposta)
        self.assertIn("- REG_CEARA", resposta)

    def test_bom_dia_retorna_saudacao_em_vez_de_alertas(self):
        resposta = self.perguntar("Bom dia SofIA")

        self.assertEqual(resposta, engine.SOFIA_INITIAL_REPLY)

    def test_resumo_regional_sem_topico_especifico(self):
        resposta = self.perguntar("resumo da regional abc")
        self.assertIn("Resumo da REG_ABC", resposta)
        self.assertIn("servidores", resposta)
        self.assertIn("links de internet", resposta)
        self.assertIn("switches", resposta)

    def test_status_links_continua_operacional(self):
        resposta = self.perguntar("como estao os links?")
        self.assertIn("Links de internet", resposta)
        self.assertIn("2 no total", resposta)
        self.assertIn("1 online", resposta)
        self.assertIn("1 offline", resposta)

    def test_alertas_switches(self):
        resposta = self.perguntar("tem alerta de switch?")
        self.assertIn("1 alerta", resposta)
        self.assertIn("SWT-ABC-01", resposta)
        self.assertIn("CPU alta", resposta)

    def test_responde_regionais_em_manutencao(self):
        resposta = self.perguntar("tem alguma regional em manutenção?")

        self.assertIn("1 regional", resposta)
        self.assertIn("REG_ABC", resposta)
        self.assertIn("MIGRACAO ABC", resposta)

    def test_responde_manutencao_de_regional_especifica(self):
        resposta = self.perguntar("a regional ABC está em manutenção?")

        self.assertIn("REG_ABC está em manutenção", resposta)

    def test_identifica_apenas_resumo_geral_para_o_n8n(self):
        self.assertTrue(engine.solicita_resumo_geral_alertas("Resumo dos alertas atuais"))
        self.assertTrue(engine.solicita_resumo_geral_alertas("Quantos alertas ativos temos agora?"))
        self.assertFalse(engine.solicita_resumo_geral_alertas("Tem alerta de switch?"))
        self.assertFalse(engine.solicita_resumo_geral_alertas("Como estao os links?"))

    def test_identifica_consulta_de_manutencao(self):
        self.assertTrue(engine.solicita_status_manutencao(
            "Tem alguma regional em manutenção?"
        ))
        self.assertFalse(engine.solicita_status_manutencao(
            "Tem alguma regional com alerta?"
        ))

    def test_identifica_respostas_factuais_locais(self):
        self.assertTrue(engine.solicita_resposta_local("Bom dia SofIA"))
        self.assertTrue(engine.solicita_resposta_local(
            "Quantas regionais temos no Sentinel?"
        ))
        self.assertTrue(engine.solicita_resposta_local("Quais são elas?"))
        self.assertFalse(engine.solicita_resposta_local(
            "Resuma os alertas atuais"
        ))

    def test_resposta_explicativa_dashboard_usa_knowledge(self):
        resposta = self.perguntar("me explica o dashboard")
        self.assertIn("Dashboard do Sentinel", resposta)
        self.assertIn("consolida informações", resposta)

    def test_resposta_explicativa_seguranca_usa_knowledge(self):
        resposta = self.perguntar("seguranca da sofia")
        self.assertIn("Segurança da SofIA", resposta)
        self.assertIn("segura por padrão", resposta)

    def test_pergunta_nao_entendida_retorna_ajuda_guiada(self):
        resposta = self.perguntar("qual e a cor do sistema?")
        self.assertIn("Ainda não entendi", resposta)
        self.assertIn("Quantas regionais temos?", resposta)
        self.assertIn("modo somente leitura", resposta)

    def test_escopo_regional_e_propagado_para_as_ferramentas(self):
        captured = {}

        def identificar(mensagem, allowed_regionals=None):
            captured["identificar"] = allowed_regionals
            return None

        def links(codigo=None, allowed_regionals=None):
            captured["links"] = allowed_regionals
            return {"total": 0}

        engine.identificar_regional = identificar
        engine.resumo_links = links
        allowed = ("REG_ABC",)

        engine.processar_mensagem_sofia(
            usuario="teste",
            mensagem="como estao os links?",
            allowed_regionals=allowed,
        )

        self.assertEqual(allowed, captured["identificar"])
        self.assertEqual(allowed, captured["links"])


if __name__ == "__main__":
    unittest.main()
