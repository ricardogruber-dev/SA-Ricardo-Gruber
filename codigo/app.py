
"""
Sistema de oficina mecânica
Lógica em Python, persistência em JSON e interface web com Flask.

Os dados são salvos automaticamente em arquivos JSON separados,
dentro da pasta "dados", localizada ao lado deste programa.

Arquivos utilizados:
- dados/consertos.json      -> consertos, peças utilizadas e comentários.
- dados/estoque.json        -> peças disponíveis no estoque.
- dados/movimentacoes.json -> histórico de entradas e saídas do estoque.
"""

# ---------------------------------------------------------------------------
# IMPORTAÇÕES
# ---------------------------------------------------------------------------

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from enum import Enum
from pathlib import Path
import json
import os

from flask import Flask, flash, redirect, render_template, request, url_for


# ---------------------------------------------------------------------------
# CONFIGURAÇÕES GERAIS
# ---------------------------------------------------------------------------

# Define a precisão monetária utilizada em todo o sistema.
# Decimal evita os problemas de precisão que podem ocorrer com float.
CENTAVO = Decimal("0.01")

# Define o local onde os arquivos JSON serão armazenados.
PASTA_DADOS = Path(__file__).with_name("dados")

# Define os caminhos da interface web.
BASE_DIR = Path(__file__).resolve().parent.parent
TEMPLATE_DIR = BASE_DIR / "interface" / "templates"
STATIC_DIR = TEMPLATE_DIR / "static"

# Lista de problemas comuns para facilitar o cadastro de consertos.
# O usuário também pode informar um problema personalizado.
PROBLEMAS_COMUNS = [
    "Motor não liga",
    "Motor falhando ou perdendo potência",
    "Superaquecimento do motor",
    "Barulho ou problema na suspensão",
    "Problema nos freios",
    "Embreagem com defeito",
    "Dificuldade para trocar as marchas",
    "Bateria descarregando ou não dando partida",
    "Vazamento de óleo ou outro fluido",
    "Problema elétrico ou nas luzes",
]


# ---------------------------------------------------------------------------
# EXCEÇÕES ESPECÍFICAS
# ---------------------------------------------------------------------------

# Exceção principal do sistema.
# As demais exceções herdam dela, permitindo tratar erros da oficina
# de maneira centralizada nas rotas do Flask.
class ErroOficina(Exception):
    """Erro esperado nas operações do sistema."""


class DadoInvalido(ErroOficina):
    """Representa um dado informado pelo usuário que não passou na validação."""


class RegistroNaoEncontrado(ErroOficina):
    """Indica que um conserto ou uma peça não foi localizado."""


class OperacaoNaoPermitida(ErroOficina):
    """Indica que uma ação não é válida para o estado atual do registro."""


class ErroArmazenamento(ErroOficina):
    """Indica falha ao ler ou gravar os arquivos JSON de dados."""


# ---------------------------------------------------------------------------
# VALIDAÇÕES E FORMATAÇÃO
# ---------------------------------------------------------------------------

def validar_texto(valor: str, campo: str) -> str:
    """
    Verifica se um campo de texto foi preenchido corretamente.

    Remove espaços desnecessários das extremidades para evitar
    registros com espaços acidentais.
    """
    if not isinstance(valor, str) or not valor.strip():
        raise DadoInvalido(f"{campo} é obrigatório.")

    return valor.strip()


def validar_inteiro_positivo(valor: int, campo: str = "Quantidade") -> int:
    """
    Garante que a quantidade informada seja um inteiro positivo.

    A verificação de bool é necessária porque, em Python,
    bool é uma subclasse de int.
    """
    if isinstance(valor, bool) or not isinstance(valor, int) or valor <= 0:
        raise DadoInvalido(f"{campo} deve ser um inteiro maior que zero.")

    return valor


def validar_dinheiro(
    valor: object, campo: str = "Valor", permitir_zero: bool = True
) -> Decimal:
    """
    Valida valores monetários e converte o resultado para Decimal.

    Também aceita vírgula como separador decimal, facilitando
    a utilização do sistema no padrão brasileiro.
    """
    try:
        numero = Decimal(str(valor).strip().replace(",", "."))
    except (InvalidOperation, ValueError, AttributeError):
        raise DadoInvalido(f"{campo} inválido.")

    # Impede valores como NaN e infinito.
    if not numero.is_finite():
        raise DadoInvalido(f"{campo} deve ser um número finito.")

    # Verifica se o valor respeita a regra definida para o campo.
    if numero < 0 or (not permitir_zero and numero == 0):
        regra = "maior que zero" if not permitir_zero else "não negativo"
        raise DadoInvalido(f"{campo} deve ser {regra}.")

    try:
        # Padroniza o valor para duas casas decimais.
        return numero.quantize(CENTAVO, rounding=ROUND_HALF_UP)
    except InvalidOperation:
        raise DadoInvalido(
            f"{campo} inválido ou fora do limite aceito."
        ) from None


def formatar_moeda(valor: Decimal) -> str:
    """Converte um valor Decimal para o formato monetário brasileiro."""
    texto = f"{Decimal(valor):,.2f}"

    return "R$ " + texto.replace(",", "X").replace(".", ",").replace("X", ".")


# ---------------------------------------------------------------------------
# MODELOS
# ---------------------------------------------------------------------------

# Enum define os estados possíveis de um conserto.
# Utilizar valores fixos evita inconsistências na situação dos registros.
class SituacaoConserto(Enum):
    PENDENTE = "Pendente"
    EM_EXECUCAO = "Em execução"
    CONCLUIDO = "Concluído"


@dataclass
class Peca:
    """
    Representa uma peça cadastrada no estoque.

    O ID identifica a peça, enquanto os preços permitem
    calcular o valor armazenado e o valor de venda.
    """
    id: int
    nome: str
    quantidade: int
    preco_custo: Decimal
    preco_venda: Decimal

    @property
    def valor_em_estoque(self) -> Decimal:
        """Calcula o valor de custo das unidades disponíveis."""
        return self.preco_custo * self.quantidade


@dataclass
class ItemUsado:
    """
    Registra uma peça utilizada em determinado conserto.

    O preço unitário é armazenado no momento da utilização.
    Dessa forma, alterações futuras no estoque não modificam
    o histórico financeiro dos consertos anteriores.
    """
    peca_id: int
    nome: str
    quantidade: int
    preco_unitario: Decimal

    @property
    def subtotal(self) -> Decimal:
        """Calcula o valor total das unidades utilizadas."""
        return self.preco_unitario * self.quantidade


@dataclass
class ComentarioMecanico:
    """Armazena uma observação feita pelo mecânico."""
    mecanico: str
    texto: str
    data: datetime = field(default_factory=datetime.now)


@dataclass
class Conserto:
    """
    Representa um atendimento realizado pela oficina.

    Centraliza os dados do cliente, veículo, problema,
    peças utilizadas, mão de obra, situação e comentários.
    """
    id: int
    cliente: str
    veiculo: str
    problema: str
    mecanico: str
    data_entrada: datetime = field(default_factory=datetime.now)
    pecas_usadas: list[ItemUsado] = field(default_factory=list)
    mao_de_obra: Decimal = Decimal("0.00")
    situacao: SituacaoConserto = SituacaoConserto.PENDENTE
    data_conclusao: datetime | None = None
    comentarios: list[ComentarioMecanico] = field(default_factory=list)

    @property
    def total_pecas(self) -> Decimal:
        """Soma os valores de todas as peças utilizadas."""
        return sum(
            (item.subtotal for item in self.pecas_usadas),
            Decimal("0.00")
        )

    @property
    def total(self) -> Decimal:
        """Calcula o valor total do conserto, incluindo a mão de obra."""
        return self.total_pecas + self.mao_de_obra


@dataclass
class MovimentacaoEstoque:
    """
    Registra uma entrada ou saída de peças.

    Esse histórico permite acompanhar as alterações do estoque
    e identificar quando uma peça foi utilizada em um conserto.
    """
    peca_id: int
    nome_peca: str
    tipo: str
    quantidade: int
    motivo: str
    data: datetime = field(default_factory=datetime.now)
    conserto_id: int | None = None


# ---------------------------------------------------------------------------
# CONVERSÃO PARA JSON
# ---------------------------------------------------------------------------

# JSON não trabalha diretamente com objetos datetime e Decimal.
# Por isso, essas funções convertem os valores para formatos compatíveis
# com JSON e permitem reconstruir os objetos quando os dados são carregados.

def _data_para_texto(data: datetime | None) -> str | None:
    """Converte uma data para texto ISO ou retorna None."""
    return data.isoformat(timespec="seconds") if data else None


def _texto_para_data(texto: str | None) -> datetime | None:
    """Reconstrói uma data a partir de seu formato ISO."""
    return datetime.fromisoformat(texto) if texto else None


def peca_para_dict(p: Peca) -> dict:
    """Transforma uma peça em um dicionário compatível com JSON."""
    return {
        "id": p.id,
        "nome": p.nome,
        "quantidade": p.quantidade,
        "preco_custo": str(p.preco_custo),
        "preco_venda": str(p.preco_venda),
    }


def peca_de_dict(d: dict) -> Peca:
    """Reconstrói um objeto Peca a partir dos dados JSON."""
    return Peca(
        id=d["id"],
        nome=d["nome"],
        quantidade=d["quantidade"],
        preco_custo=Decimal(d["preco_custo"]),
        preco_venda=Decimal(d["preco_venda"]),
    )


def conserto_para_dict(c: Conserto) -> dict:
    """
    Converte um conserto completo para dicionário.

    Também converte suas peças e comentários, preservando
    os relacionamentos dentro do registro.
    """
    return {
        "id": c.id,
        "cliente": c.cliente,
        "veiculo": c.veiculo,
        "problema": c.problema,
        "mecanico": c.mecanico,
        "data_entrada": _data_para_texto(c.data_entrada),
        "pecas_usadas": [
            {
                "peca_id": i.peca_id,
                "nome": i.nome,
                "quantidade": i.quantidade,
                "preco_unitario": str(i.preco_unitario),
            }
            for i in c.pecas_usadas
        ],
        "mao_de_obra": str(c.mao_de_obra),
        "situacao": c.situacao.value,
        "data_conclusao": _data_para_texto(c.data_conclusao),
        "comentarios": [
            {
                "mecanico": m.mecanico,
                "texto": m.texto,
                "data": _data_para_texto(m.data),
            }
            for m in c.comentarios
        ],
    }


def conserto_de_dict(d: dict) -> Conserto:
    """Reconstrói um conserto completo a partir de um dicionário JSON."""
    return Conserto(
        id=d["id"],
        cliente=d["cliente"],
        veiculo=d["veiculo"],
        problema=d["problema"],
        mecanico=d["mecanico"],
        data_entrada=_texto_para_data(d["data_entrada"]),
        pecas_usadas=[
            ItemUsado(
                peca_id=i["peca_id"],
                nome=i["nome"],
                quantidade=i["quantidade"],
                preco_unitario=Decimal(i["preco_unitario"]),
            )
            for i in d["pecas_usadas"]
        ],
        mao_de_obra=Decimal(d["mao_de_obra"]),
        situacao=SituacaoConserto(d["situacao"]),
        data_conclusao=_texto_para_data(d["data_conclusao"]),
        comentarios=[
            ComentarioMecanico(
                mecanico=m["mecanico"],
                texto=m["texto"],
                data=_texto_para_data(m["data"]),
            )
            for m in d["comentarios"]
        ],
    )


def movimentacao_para_dict(m: MovimentacaoEstoque) -> dict:
    """Transforma uma movimentação em um dicionário JSON."""
    return {
        "peca_id": m.peca_id,
        "nome_peca": m.nome_peca,
        "tipo": m.tipo,
        "quantidade": m.quantidade,
        "motivo": m.motivo,
        "data": _data_para_texto(m.data),
        "conserto_id": m.conserto_id,
    }


def movimentacao_de_dict(d: dict) -> MovimentacaoEstoque:
    """Reconstrói uma movimentação a partir dos dados JSON."""
    return MovimentacaoEstoque(
        peca_id=d["peca_id"],
        nome_peca=d["nome_peca"],
        tipo=d["tipo"],
        quantidade=d["quantidade"],
        motivo=d["motivo"],
        data=_texto_para_data(d["data"]),
        conserto_id=d["conserto_id"],
    )


# ---------------------------------------------------------------------------
# REGRAS DE NEGÓCIO
# ---------------------------------------------------------------------------

class Oficina:
    """
    Centraliza os dados e as operações da oficina.

    Essa classe é responsável por aplicar as regras de negócio,
    consultar registros, controlar o estoque e persistir os dados.

    O Flask utiliza essa classe para executar as operações,
    mantendo as regras de negócio separadas da interface web.
    """

    def __init__(self, pasta: Path | None = None) -> None:
        """Inicializa as listas e carrega os dados existentes."""
        self.pasta = pasta
        self.consertos: list[Conserto] = []
        self.estoque: list[Peca] = []
        self.movimentacoes: list[MovimentacaoEstoque] = []

        # Os identificadores começam em 1 quando não existem registros.
        self._proximo_id_conserto = 1
        self._proximo_id_peca = 1

        if pasta is not None:
            self._carregar()

    # -----------------------------------------------------------------------
    # PERSISTÊNCIA
    # -----------------------------------------------------------------------

    def _carregar_parte(
        self, nome: str, converter: Callable[[dict], object]
    ) -> list:
        """
        Carrega um arquivo JSON e converte seus registros em objetos.

        O conversor recebido permite utilizar o mesmo método
        para carregar consertos, peças e movimentações.
        """
        caminho = self.pasta / f"{nome}.json"

        # Se o arquivo ainda não existe, inicia com uma lista vazia.
        if not caminho.exists():
            return []

        try:
            with caminho.open(encoding="utf-8") as f:
                return [converter(item) for item in json.load(f)]

        except (
            OSError, ValueError, KeyError, TypeError, InvalidOperation
        ) as erro:
            # Não sobrescreve automaticamente arquivos com problemas.
            # Isso evita perder dados que possam ser recuperados.
            raise ErroArmazenamento(
                f"Não foi possível ler '{caminho.name}' ({erro}). "
                "O arquivo foi mantido sem alterações; corrija-o ou renomeie-o "
                "para começar com dados novos."
            ) from erro

    def _carregar(self) -> None:
        """
        Carrega todos os arquivos de dados da oficina.

        Depois da leitura, identifica o maior ID existente para que
        os próximos cadastros continuem a sequência corretamente.
        """
        self.estoque = self._carregar_parte("estoque", peca_de_dict)
        self.consertos = self._carregar_parte("consertos", conserto_de_dict)

        self.movimentacoes = self._carregar_parte(
            "movimentacoes", movimentacao_de_dict
        )

        # Evita reutilizar identificadores após reiniciar o sistema.
        self._proximo_id_conserto = max(
            (c.id for c in self.consertos), default=0
        ) + 1

        self._proximo_id_peca = max(
            (p.id for p in self.estoque), default=0
        ) + 1

    def salvar(self, *partes: str) -> None:
        """
        Persiste os dados nos arquivos JSON.

        Permite salvar somente as partes alteradas ou todos os arquivos.
        A gravação é feita primeiro em um arquivo temporário.
        Depois, os.replace() substitui o arquivo original.
        """
        if self.pasta is None:
            return

        conversores = {
            "consertos": lambda: [
                conserto_para_dict(c) for c in self.consertos
            ],
            "estoque": lambda: [
                peca_para_dict(p) for p in self.estoque
            ],
            "movimentacoes": lambda: [
                movimentacao_para_dict(m) for m in self.movimentacoes
            ],
        }

        try:
            # Cria a pasta de dados caso ela ainda não exista.
            self.pasta.mkdir(parents=True, exist_ok=True)

            # Se nenhuma parte for informada, salva todos os arquivos.
            for nome in partes or conversores:
                caminho = self.pasta / f"{nome}.json"
                temporario = caminho.with_suffix(".tmp")

                with temporario.open("w", encoding="utf-8") as f:
                    json.dump(
                        conversores[nome](),
                        f,
                        ensure_ascii=False,
                        indent=2
                    )

                # Substitui o arquivo original somente após terminar a gravação.
                os.replace(temporario, caminho)

        except OSError as erro:
            raise ErroArmazenamento(
                f"Não foi possível salvar os dados: {erro}"
            ) from erro

    # -----------------------------------------------------------------------
    # BUSCAS
    # -----------------------------------------------------------------------

    def buscar_conserto_por_id(self, conserto_id: int) -> Conserto:
        """Localiza um conserto pelo seu identificador."""
        for conserto in self.consertos:
            if conserto.id == conserto_id:
                return conserto

        raise RegistroNaoEncontrado("Conserto não encontrado.")

    def buscar_peca_por_id(self, peca_id: int) -> Peca:
        """Localiza uma peça pelo seu identificador."""
        for peca in self.estoque:
            if peca.id == peca_id:
                return peca

        raise RegistroNaoEncontrado("Peça não encontrada.")

    def buscar_consertos_por_texto(self, texto: str) -> list[Conserto]:
        """
        Pesquisa consertos por diferentes informações.

        A busca não diferencia letras maiúsculas de minúsculas,
        facilitando a localização dos registros.
        """
        termo = validar_texto(texto, "Busca").casefold()

        return [
            c for c in self.consertos
            if termo in c.cliente.casefold()
            or termo in c.veiculo.casefold()
            or termo in c.mecanico.casefold()
            or termo in c.problema.casefold()
            or termo in c.situacao.value.casefold()
        ]

    # -----------------------------------------------------------------------
    # CONSERTOS
    # -----------------------------------------------------------------------

    def cadastrar_conserto(
        self, cliente: str, veiculo: str, problema: str, mecanico: str
    ) -> Conserto:
        """
        Cadastra um novo atendimento.

        Todos os campos obrigatórios são validados antes da criação.
        O conserto começa automaticamente com situação pendente.
        """
        dados = (
            validar_texto(cliente, "Cliente"),
            validar_texto(veiculo, "Veículo"),
            validar_texto(problema, "Problema"),
            validar_texto(mecanico, "Mecânico"),
        )

        conserto = Conserto(self._proximo_id_conserto, *dados)

        self.consertos.append(conserto)
        self._proximo_id_conserto += 1

        # Salva imediatamente para não perder o cadastro.
        self.salvar("consertos")

        return conserto

    def listar_consertos(
        self, situacao: SituacaoConserto | None = None
    ) -> list[Conserto]:
        """Lista todos os consertos ou filtra por situação."""
        if situacao is None:
            return list(self.consertos)

        return [
            c for c in self.consertos
            if c.situacao == situacao
        ]

    def iniciar_conserto(self, conserto_id: int) -> Conserto:
        """
        Altera a situação de um conserto pendente para em execução.

        Essa verificação impede que um conserto concluído
        ou já iniciado seja iniciado novamente.
        """
        conserto = self.buscar_conserto_por_id(conserto_id)

        if conserto.situacao != SituacaoConserto.PENDENTE:
            raise OperacaoNaoPermitida(
                "Somente um conserto pendente pode ser iniciado."
            )

        conserto.situacao = SituacaoConserto.EM_EXECUCAO

        self.salvar("consertos")

        return conserto

    def adicionar_comentario(
        self, conserto_id: int, mecanico: str, texto: str
    ) -> Conserto:
        """
        Registra uma observação no histórico do conserto.

        Não permite adicionar comentários depois da conclusão,
        preservando o histórico do atendimento finalizado.
        """
        conserto = self.buscar_conserto_por_id(conserto_id)

        if conserto.situacao == SituacaoConserto.CONCLUIDO:
            raise OperacaoNaoPermitida(
                "Não é possível comentar um conserto concluído."
            )

        mecanico = validar_texto(mecanico, "Mecânico")
        texto = validar_texto(texto, "Comentário")

        conserto.comentarios.append(
            ComentarioMecanico(mecanico=mecanico, texto=texto)
        )

        self.salvar("consertos")

        return conserto

    def concluir_conserto(
        self, conserto_id: int, mao_de_obra: Decimal
    ) -> Conserto:
        """
        Finaliza um conserto e registra o valor da mão de obra.

        Somente consertos pendentes ou em execução podem ser concluídos.
        A data de conclusão é registrada automaticamente.
        """
        conserto = self.buscar_conserto_por_id(conserto_id)

        if conserto.situacao not in (
            SituacaoConserto.PENDENTE,
            SituacaoConserto.EM_EXECUCAO
        ):
            raise OperacaoNaoPermitida(
                "Este conserto não pode ser concluído."
            )

        conserto.mao_de_obra = validar_dinheiro(
            mao_de_obra, "Mão de obra"
        )

        conserto.situacao = SituacaoConserto.CONCLUIDO
        conserto.data_conclusao = datetime.now()

        self.salvar("consertos")

        return conserto

    # -----------------------------------------------------------------------
    # ESTOQUE
    # -----------------------------------------------------------------------

    def adicionar_peca(
        self,
        nome: str,
        quantidade: int,
        preco_custo: Decimal,
        preco_venda: Decimal | None = None,
    ) -> Peca:
        """
        Adiciona uma peça ao estoque.

        Se a peça já existir, aumenta sua quantidade e atualiza os preços.
        Caso contrário, cria um novo registro com identificador próprio.

        Toda entrada também gera uma movimentação no histórico.
        """
        nome = validar_texto(nome, "Nome da peça")
        quantidade = validar_inteiro_positivo(quantidade)

        custo = validar_dinheiro(preco_custo, "Preço de custo")

        venda = validar_dinheiro(
            custo if preco_venda is None else preco_venda,
            "Preço de venda"
        )

        # Verifica se já existe uma peça com o mesmo nome.
        for peca in self.estoque:
            if peca.nome.casefold() == nome.casefold():

                # Atualiza a quantidade e os preços da peça existente.
                peca.quantidade += quantidade
                peca.preco_custo = custo
                peca.preco_venda = venda

                # Registra a entrada para manter o histórico do estoque.
                self.movimentacoes.append(
                    MovimentacaoEstoque(
                        peca.id,
                        peca.nome,
                        "Entrada",
                        quantidade,
                        "Reposição de estoque"
                    )
                )

                self.salvar("estoque", "movimentacoes")

                return peca

        # Se a peça não existir, cria um novo registro.
        peca = Peca(
            self._proximo_id_peca,
            nome,
            quantidade,
            custo,
            venda
        )

        self.estoque.append(peca)
        self._proximo_id_peca += 1

        # O cadastro inicial também é registrado como entrada.
        self.movimentacoes.append(
            MovimentacaoEstoque(
                peca.id,
                peca.nome,
                "Entrada",
                quantidade,
                "Cadastro inicial"
            )
        )

        self.salvar("estoque", "movimentacoes")

        return peca

    def usar_peca(
        self, conserto_id: int, peca_id: int, quantidade: int
    ) -> ItemUsado:
        """
        Registra a utilização de uma peça em um conserto.

        Atualiza o estoque, adiciona a peça ao atendimento,
        altera a situação do conserto e registra a saída.
        """
        conserto = self.buscar_conserto_por_id(conserto_id)
        peca = self.buscar_peca_por_id(peca_id)

        quantidade = validar_inteiro_positivo(quantidade)

        # Impede alterações em consertos já concluídos.
        if conserto.situacao not in (
            SituacaoConserto.PENDENTE,
            SituacaoConserto.EM_EXECUCAO
        ):
            raise OperacaoNaoPermitida(
                "Não é possível alterar as peças deste conserto."
            )

        # Confere a disponibilidade antes de retirar qualquer unidade.
        if peca.quantidade < quantidade:
            raise OperacaoNaoPermitida(
                f"Estoque insuficiente. Quantidade disponível: {peca.quantidade}."
            )

        # Guarda o preço atual para preservar o valor histórico do conserto.
        item = ItemUsado(
            peca.id,
            peca.nome,
            quantidade,
            peca.preco_venda
        )

        # Atualiza os registros relacionados à utilização da peça.
        peca.quantidade -= quantidade
        conserto.pecas_usadas.append(item)
        conserto.situacao = SituacaoConserto.EM_EXECUCAO

        # Registra a saída e relaciona a movimentação ao conserto.
        self.movimentacoes.append(
            MovimentacaoEstoque(
                peca.id,
                peca.nome,
                "Saída",
                quantidade,
                f"Utilização no conserto #{conserto.id}",
                conserto_id=conserto.id
            )
        )

        # As três partes precisam ser salvas porque foram alteradas.
        self.salvar("consertos", "estoque", "movimentacoes")

        return item

    def calcular_valor_em_estoque(self) -> Decimal:
        """Calcula o valor total de custo das peças disponíveis."""
        return sum(
            (p.valor_em_estoque for p in self.estoque),
            Decimal("0.00")
        )

    def calcular_faturamento(self) -> Decimal:
        """
        Calcula o faturamento dos consertos concluídos.

        Atendimentos pendentes ou em execução não entram no cálculo.
        """
        return sum(
            (
                c.total for c in self.consertos
                if c.situacao == SituacaoConserto.CONCLUIDO
            ),
            Decimal("0.00")
        )


# ---------------------------------------------------------------------------
# APLICAÇÃO WEB (FLASK)
# ---------------------------------------------------------------------------

def criar_app() -> Flask:
    """
    Cria e configura a aplicação Flask.

    Conecta a interface HTML às regras de negócio da classe Oficina.
    Cada rota representa uma funcionalidade acessível pelo navegador.
    """

    # Informa ao Flask onde estão os templates e os arquivos estáticos.
    app = Flask(
        __name__,
        template_folder=str(TEMPLATE_DIR),
        static_folder=str(STATIC_DIR),
    )

    # A chave secreta é utilizada pelo Flask para proteger sessões e mensagens.
    # Em produção, deve ser configurada por variável de ambiente.
    app.secret_key = os.environ.get(
        "FLASK_SECRET_KEY",
        "oficina-dev-key"
    )

    # Instancia a oficina uma única vez para manter os dados disponíveis
    # durante a execução da aplicação.
    oficina = Oficina(PASTA_DADOS)

    # -----------------------------------------------------------------------
    # PÁGINA INICIAL
    # -----------------------------------------------------------------------

    @app.route("/")
    def index():
        """Exibe o painel principal com os indicadores da oficina."""

        consertos = oficina.listar_consertos()

        # Reúne os dados necessários para preencher os indicadores do HTML.
        resumo = {
            "total_consertos": len(consertos),

            "pendentes": len(
                oficina.listar_consertos(SituacaoConserto.PENDENTE)
            ),

            "em_execucao": len(
                oficina.listar_consertos(SituacaoConserto.EM_EXECUCAO)
            ),

            "concluidos": len(
                oficina.listar_consertos(SituacaoConserto.CONCLUIDO)
            ),

            "faturamento": formatar_moeda(
                oficina.calcular_faturamento()
            ),

            "valor_estoque": formatar_moeda(
                oficina.calcular_valor_em_estoque()
            ),
        }

        return render_template("index.html", resumo=resumo)

    # -----------------------------------------------------------------------
    # CADASTRO DE CONSERTOS
    # -----------------------------------------------------------------------

    @app.route("/cadastrar", methods=["GET", "POST"])
    def cadastrar():
        """
        Exibe o formulário e processa novos cadastros.

        GET apresenta a página.
        POST recebe os dados enviados pelo formulário HTML.
        """

        if request.method == "POST":

            # Recupera os valores enviados pelo formulário.
            cliente = request.form.get("cliente", "")
            veiculo = request.form.get("veiculo", "")
            mecanico = request.form.get("mecanico", "")

            problema_sel = request.form.get("problema", "").strip()
            problema_outro = request.form.get("problema_outro", "")

            # Permite escolher um problema comum ou informar outro.
            problema = (
                problema_outro
                if problema_sel == "outro"
                else problema_sel
            )

            try:
                conserto = oficina.cadastrar_conserto(
                    cliente,
                    veiculo,
                    problema,
                    mecanico
                )

                flash(
                    f"Conserto #{conserto.id} cadastrado com sucesso.",
                    "sucesso"
                )

                # Após cadastrar, direciona o usuário aos detalhes.
                # Isso também evita reenviar o formulário ao atualizar a página.
                return redirect(
                    url_for(
                        "detalhe_conserto",
                        conserto_id=conserto.id
                    )
                )

            except ErroOficina as erro:
                flash(str(erro), "erro")

                # Mantém os dados preenchidos para evitar que o usuário
                # precise digitar tudo novamente após uma validação inválida.
                return render_template(
                    "cadastrar.html",
                    problemas=PROBLEMAS_COMUNS,
                    form_dados={
                        "cliente": cliente,
                        "veiculo": veiculo,
                        "mecanico": mecanico,
                        "problema": problema_sel,
                        "problema_outro": problema_outro,
                    },
                )

        # Quando a página é acessada por GET, apenas exibe o formulário.
        return render_template(
            "cadastrar.html",
            problemas=PROBLEMAS_COMUNS
        )

    # -----------------------------------------------------------------------
    # LISTAGEM E PESQUISA DE CONSERTOS
    # -----------------------------------------------------------------------

    @app.route("/consertos")
    def listar_consertos():
        """Exibe os consertos e permite pesquisar e filtrar os registros."""

        termo = request.args.get("q", "").strip()
        situacao_filtro = request.args.get("situacao", "").strip()

        try:
            # Aplica a pesquisa textual, o filtro de situação ou ambos.
            if termo:
                consertos = oficina.buscar_consertos_por_texto(termo)

                if situacao_filtro:
                    situacao_enum = SituacaoConserto(situacao_filtro)

                    consertos = [
                        c for c in consertos
                        if c.situacao == situacao_enum
                    ]

            elif situacao_filtro:
                situacao_enum = SituacaoConserto(situacao_filtro)
                consertos = oficina.listar_consertos(situacao_enum)

            else:
                consertos = oficina.listar_consertos()

        except (ErroOficina, ValueError) as erro:
            # Trata filtros inválidos sem interromper a aplicação.
            flash(str(erro), "erro")
            consertos = oficina.listar_consertos()

        # Envia os registros e os filtros atuais para o template.
        return render_template(
            "consertos.html",
            consertos=consertos,
            termo=termo,
            situacao_filtro=situacao_filtro,
            situacoes=list(SituacaoConserto),
        )

    # -----------------------------------------------------------------------
    # DETALHES E GERENCIAMENTO DE UM CONSERTO
    # -----------------------------------------------------------------------

    @app.route(
        "/consertos/<int:conserto_id>",
        methods=["GET", "POST"]
    )
    def detalhe_conserto(conserto_id: int):
        """
        Exibe os detalhes de um atendimento e processa suas operações.

        A rota concentra ações como utilizar peças, adicionar comentários,
        iniciar e concluir um conserto.
        """

        # Primeiro verifica se o conserto informado realmente existe.
        try:
            conserto = oficina.buscar_conserto_por_id(conserto_id)

        except RegistroNaoEncontrado as erro:
            flash(str(erro), "erro")
            return redirect(url_for("listar_consertos"))

        if request.method == "POST":

            # Identifica qual operação foi solicitada pelo formulário.
            acao = request.form.get("acao", "").strip()

            try:

                # -----------------------------------------------------------
                # UTILIZAR PEÇA
                # -----------------------------------------------------------

                if acao == "usar_peca":

                    peca_id = int(request.form.get("peca", "0"))
                    quantidade = int(
                        request.form.get("quantidade", "0")
                    )

                    item = oficina.usar_peca(
                        conserto_id,
                        peca_id,
                        quantidade
                    )

                    flash(
                        f"Peça registrada: {item.nome} x{item.quantidade} "
                        f"({formatar_moeda(item.subtotal)}).",
                        "sucesso",
                    )

                # -----------------------------------------------------------
                # ADICIONAR COMENTÁRIO
                # -----------------------------------------------------------

                elif acao == "comentar":

                    texto = request.form.get("comentario", "")

                    oficina.adicionar_comentario(
                        conserto_id,
                        conserto.mecanico,
                        texto
                    )

                    flash("Comentário salvo.", "sucesso")

                # -----------------------------------------------------------
                # INICIAR OU MANTER EM EXECUÇÃO
                # -----------------------------------------------------------

                elif acao == "manter":

                    # Só altera o estado quando ainda está pendente.
                    if conserto.situacao == SituacaoConserto.PENDENTE:
                        oficina.iniciar_conserto(conserto_id)

                    flash(
                        "Conserto mantido em execução.",
                        "sucesso"
                    )

                # -----------------------------------------------------------
                # CONCLUIR CONSERTO
                # -----------------------------------------------------------

                elif acao == "concluir":

                    # Valida o valor antes de concluir o atendimento.
                    mao_de_obra = validar_dinheiro(
                        request.form.get("mao_de_obra", ""),
                        "Mão de obra"
                    )

                    oficina.concluir_conserto(
                        conserto_id,
                        mao_de_obra
                    )

                    flash(
                        "Conserto concluído com sucesso.",
                        "sucesso"
                    )

                else:
                    flash("Ação inválida.", "erro")

            except ValueError:
                # Trata problemas de conversão de números enviados pelo HTML.
                flash("Informe valores numéricos válidos.", "erro")

            except ErroOficina as erro:
                # Exibe erros de negócio sem interromper a aplicação.
                flash(str(erro), "erro")

            # Redireciona após processar a ação.
            # Esse padrão evita o reenvio do formulário ao atualizar a página.
            return redirect(
                url_for(
                    "detalhe_conserto",
                    conserto_id=conserto_id
                )
            )

        # No GET, apresenta os dados atuais do conserto e do estoque.
        return render_template(
            "detalhe.html",
            conserto=conserto,
            estoque=oficina.estoque,
            formatar_moeda=formatar_moeda,
        )

    # -----------------------------------------------------------------------
    # GERENCIAMENTO DO ESTOQUE
    # -----------------------------------------------------------------------

    @app.route("/estoque", methods=["GET", "POST"])
    def estoque():
        """
        Exibe o estoque e processa a entrada de novas peças.

        Quando uma peça já existe, a quantidade é somada ao estoque.
        """

        if request.method == "POST":

            nome = request.form.get("nome", "")

            try:
                quantidade = int(
                    request.form.get("quantidade", "0")
                )

                custo = validar_dinheiro(
                    request.form.get("custo", ""),
                    "Preço de custo"
                )

                venda = validar_dinheiro(
                    request.form.get("venda", ""),
                    "Preço de venda"
                )

                peca = oficina.adicionar_peca(
                    nome,
                    quantidade,
                    custo,
                    venda
                )

                flash(
                    f"Estoque atualizado: {peca.nome} "
                    f"({peca.quantidade} un.).",
                    "sucesso",
                )

                return redirect(url_for("estoque"))

            except ValueError:
                flash(
                    "Quantidade deve ser um número inteiro válido.",
                    "erro"
                )

            except ErroOficina as erro:
                flash(str(erro), "erro")

        # Apresenta as peças cadastradas e o valor total do estoque.
        return render_template(
            "estoque.html",
            pecas=oficina.estoque,
            valor_estoque=formatar_moeda(
                oficina.calcular_valor_em_estoque()
            ),
            formatar_moeda=formatar_moeda,
        )

    # -----------------------------------------------------------------------
    # HISTÓRICO DE MOVIMENTAÇÕES
    # -----------------------------------------------------------------------

    @app.route("/historico")
    def historico():
        """Exibe as movimentações do estoque da mais recente para a mais antiga."""

        # Reverte a lista para apresentar primeiro as operações mais recentes.
        movimentacoes = list(reversed(oficina.movimentacoes))

        return render_template(
            "historico.html",
            movimentacoes=movimentacoes
        )

    # Retorna a aplicação configurada para ser executada pelo servidor.
    return app


# ---------------------------------------------------------------------------
# INICIALIZAÇÃO DA APLICAÇÃO
# ---------------------------------------------------------------------------

# Cria a instância principal do Flask.
# Essa variável também é utilizada por servidores WSGI em produção.
app = criar_app()


# Executa o servidor de desenvolvimento somente quando este arquivo
# é executado diretamente, e não quando é importado por outro módulo.
if __name__ == "__main__":
    app.run(debug=True, use_reloader=False)