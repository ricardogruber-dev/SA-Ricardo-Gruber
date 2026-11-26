"""
Sistema de oficina mecânica
Lógica em Python, persistência em JSON e interface web com Flask.

Os dados são salvos automaticamente em arquivos JSON separados,
dentro da pasta "dados", localizada na raiz do projeto (fora da pasta do código).
Para usar outro local, defina a variável de ambiente OFICINA_DADOS.

Arquivos utilizados:
- dados/consertos.json      -> consertos, peças utilizadas e comentários.
- dados/estoque.json        -> peças disponíveis no estoque.
- dados/movimentacoes.json -> histórico de entradas e saídas do estoque.
"""

# ---------------------------------------------------------------------------
# IMPORTAÇÕES
# ---------------------------------------------------------------------------
from collections.abc import Callable
from contextlib import contextmanager, suppress
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from enum import Enum
from pathlib import Path
import json
import os
import unicodedata
from flask import Flask, flash, redirect, render_template, request, url_for

# ---------------------------------------------------------------------------
# CONFIGURAÇÕES GERAIS
# ---------------------------------------------------------------------------
CENTAVO = Decimal("0.01")
BASE_DIR = Path(__file__).resolve().parent.parent
PASTA_DADOS = Path(os.environ.get("OFICINA_DADOS", BASE_DIR / "dados")).resolve()
TEMPLATE_DIR = BASE_DIR / "interface" / "templates"
STATIC_DIR = TEMPLATE_DIR / "static"

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
    Remove espaços desnecessários das extremidades.
    """
    if not isinstance(valor, str) or not valor.strip():
        raise DadoInvalido(f"{campo} é obrigatório.")
    return valor.strip()


def normalizar_texto(texto: str) -> str:
    """
    Prepara um texto para comparações em buscas, ignorando maiúsculas e acentos.
    """
    decomposto = unicodedata.normalize("NFD", texto.casefold())
    return "".join(c for c in decomposto if unicodedata.category(c) != "Mn")


def validar_inteiro_positivo(valor: int, campo: str = "Quantidade") -> int:
    """Garante que a quantidade informada seja um inteiro maior que zero."""
    if isinstance(valor, bool) or not isinstance(valor, int) or valor <= 0:
        raise DadoInvalido(f"{campo} deve ser um inteiro maior que zero.")
    return valor


def validar_inteiro_nao_negativo(valor: int, campo: str = "Quantidade") -> int:
    """Garante que a quantidade informada seja um inteiro maior ou igual a zero."""
    if isinstance(valor, bool) or not isinstance(valor, int) or valor < 0:
        raise DadoInvalido(f"{campo} deve ser um número inteiro não negativo.")
    return valor


def validar_dinheiro(
    valor: object, campo: str = "Valor", permitir_zero: bool = True
) -> Decimal:
    """
    Valida valores monetários e converte o resultado para Decimal.
    Aceita vírgula ou ponto como separador decimal.
    """
    try:
        numero = Decimal(str(valor).strip().replace(",", "."))
    except (InvalidOperation, ValueError, AttributeError):
        raise DadoInvalido(f"{campo} inválido.")
    if not numero.is_finite():
        raise DadoInvalido(f"{campo} deve ser um número finito.")
    if numero < 0 or (not permitir_zero and numero == 0):
        regra = "maior que zero" if not permitir_zero else "não negativo"
        raise DadoInvalido(f"{campo} deve ser {regra}.")
    try:
        return numero.quantize(CENTAVO, rounding=ROUND_HALF_UP)
    except InvalidOperation:
        raise DadoInvalido(
            f"{campo} inválido ou fora do limite aceito."
        ) from None


def formatar_moeda(valor: Decimal) -> str:
    """Converte um valor Decimal para o formato monetário brasileiro."""
    texto = f"{Decimal(valor):,.2f}"
    return "R$ " + texto.replace(",", "X").replace(".", ",").replace("X", ".")


def formatar_decimal_input(valor: Decimal) -> str:
    """Formata um valor Decimal com vírgula para preenchimento em inputs HTML."""
    return f"{Decimal(valor):.2f}".replace(".", ",")


# ---------------------------------------------------------------------------
# MODELOS
# ---------------------------------------------------------------------------
class SituacaoConserto(Enum):
    PENDENTE = "Pendente"
    EM_EXECUCAO = "Em execução"
    CONCLUIDO = "Concluído"
    CANCELADO = "Cancelado"


@dataclass
class Peca:
    """Representa uma peça cadastrada no estoque."""
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
    O preço unitário é armazenado no momento da utilização para preservar
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
    """Representa um atendimento realizado pela oficina."""
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
    """Registra uma movimentação (entrada, saída, edição ou exclusão) de peças."""
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
    """Converte um conserto completo para dicionário."""
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
    """

    def __init__(self, pasta: Path | None = None) -> None:
        """Inicializa as listas e carrega os dados existentes."""
        self.pasta = pasta
        self.consertos: list[Conserto] = []
        self.estoque: list[Peca] = []
        self.movimentacoes: list[MovimentacaoEstoque] = []
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
        """Carrega um arquivo JSON e converte seus registros em objetos."""
        caminho = self.pasta / f"{nome}.json"
        if not caminho.exists():
            return []
        try:
            texto = caminho.read_text(encoding="utf-8")
            if not texto.strip():
                return []
            return [converter(item) for item in json.loads(texto)]
        except (
            OSError, ValueError, KeyError, TypeError, InvalidOperation
        ) as erro:
            raise ErroArmazenamento(
                f"Não foi possível ler '{caminho.name}' ({erro}). "
                "O arquivo foi mantido sem alterações; corrija-o ou renomeie-o "
                "para começar com dados novos."
            ) from erro

    def _carregar(self) -> None:
        """Carrega todos os arquivos de dados da oficina."""
        self.estoque = self._carregar_parte("estoque", peca_de_dict)
        self.consertos = self._carregar_parte("consertos", conserto_de_dict)
        self.movimentacoes = self._carregar_parte(
            "movimentacoes", movimentacao_de_dict
        )
        self._proximo_id_conserto = max(
            (c.id for c in self.consertos), default=0
        ) + 1
        max_id_estoque = max((p.id for p in self.estoque), default=0)
        max_id_mov = max((m.peca_id for m in self.movimentacoes), default=0)
        self._proximo_id_peca = max(max_id_estoque, max_id_mov) + 1

    @contextmanager
    def _transacao(self):
        """Desfaz as alterações em memória se a operação falhar."""
        estado = (
            deepcopy(self.consertos),
            deepcopy(self.estoque),
            deepcopy(self.movimentacoes),
            self._proximo_id_conserto,
            self._proximo_id_peca,
        )
        try:
            yield
        except Exception:
            (
                self.consertos,
                self.estoque,
                self.movimentacoes,
                self._proximo_id_conserto,
                self._proximo_id_peca,
            ) = estado
            raise

    def salvar(self, *partes: str) -> None:
        """Persiste os dados nos arquivos JSON de maneira atômica."""
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
        alvos = []
        for nome in partes or conversores:
            caminho = self.pasta / f"{nome}.json"
            alvos.append((nome, caminho, caminho.with_suffix(".tmp")))
        try:
            self.pasta.mkdir(parents=True, exist_ok=True)
            for nome, _, temporario in alvos:
                with temporario.open("w", encoding="utf-8") as f:
                    json.dump(
                        conversores[nome](),
                        f,
                        ensure_ascii=False,
                        indent=2
                    )
            for _, caminho, temporario in alvos:
                os.replace(temporario, caminho)
        except OSError as erro:
            for _, _, temporario in alvos:
                with suppress(OSError):
                    temporario.unlink(missing_ok=True)
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
        """Pesquisa consertos por cliente, veículo, mecânico, problema ou situação."""
        termo = normalizar_texto(validar_texto(texto, "Busca"))
        return [
            c for c in self.consertos
            if any(
                termo in normalizar_texto(campo)
                for campo in (
                    c.cliente,
                    c.veiculo,
                    c.mecanico,
                    c.problema,
                    c.situacao.value,
                )
            )
        ]

    # -----------------------------------------------------------------------
    # CONSERTOS
    # -----------------------------------------------------------------------
    def cadastrar_conserto(
        self, cliente: str, veiculo: str, problema: str, mecanico: str
    ) -> Conserto:
        """Cadastra um novo atendimento com situação pendente."""
        dados = (
            validar_texto(cliente, "Cliente"),
            validar_texto(veiculo, "Veículo"),
            validar_texto(problema, "Problema"),
            validar_texto(mecanico, "Mecânico"),
        )
        with self._transacao():
            conserto = Conserto(self._proximo_id_conserto, *dados)
            self.consertos.append(conserto)
            self._proximo_id_conserto += 1
            self.salvar("consertos")
        return conserto

    def listar_consertos(
        self, situacao: SituacaoConserto | None = None
    ) -> list[Conserto]:
        """Lista todos os consertos ou filtra por situação."""
        if situacao is None:
            return list(self.consertos)
        return [c for c in self.consertos if c.situacao == situacao]

    def iniciar_conserto(self, conserto_id: int) -> Conserto:
        """Altera a situação de um conserto pendente para em execução."""
        conserto = self.buscar_conserto_por_id(conserto_id)
        if conserto.situacao != SituacaoConserto.PENDENTE:
            raise OperacaoNaoPermitida(
                "Somente um conserto pendente pode ser iniciado."
            )
        with self._transacao():
            conserto.situacao = SituacaoConserto.EM_EXECUCAO
            self.salvar("consertos")
        return conserto

    def editar_conserto(
        self,
        conserto_id: int,
        cliente: str,
        veiculo: str,
        mecanico: str,
        problema: str,
        mao_de_obra: object,
    ) -> Conserto:
        """
        Atualiza os dados cadastrais e a mão de obra de um conserto ativo.
        Não altera peças utilizadas nem movimentações anteriores do estoque.
        """
        conserto = self.buscar_conserto_por_id(conserto_id)
        if conserto.situacao in (
            SituacaoConserto.CONCLUIDO,
            SituacaoConserto.CANCELADO,
        ):
            raise OperacaoNaoPermitida(
                "Não é possível editar um conserto concluído ou cancelado."
            )
        cliente_val = validar_texto(cliente, "Nome do cliente")
        veiculo_val = validar_texto(veiculo, "Nome do veículo")
        mecanico_val = validar_texto(mecanico, "Nome do mecânico")
        problema_val = validar_texto(problema, "Descrição do problema")
        mao_de_obra_val = validar_dinheiro(mao_de_obra, "Valor da mão de obra")

        with self._transacao():
            conserto.cliente = cliente_val
            conserto.veiculo = veiculo_val
            conserto.mecanico = mecanico_val
            conserto.problema = problema_val
            conserto.mao_de_obra = mao_de_obra_val
            self.salvar("consertos")
        return conserto

    def cancelar_conserto(self, conserto_id: int) -> Conserto:
        """
        Cancela um conserto ativo e devolve automaticamente ao estoque
        todas as peças utilizadas nele, registrando cada devolução no histórico.
        """
        conserto = self.buscar_conserto_por_id(conserto_id)
        if conserto.situacao == SituacaoConserto.CONCLUIDO:
            raise OperacaoNaoPermitida(
                "Não é possível cancelar um conserto que já está concluído."
            )
        if conserto.situacao == SituacaoConserto.CANCELADO:
            raise OperacaoNaoPermitida(
                "Este conserto já está cancelado."
            )

        with self._transacao():
            conserto.situacao = SituacaoConserto.CANCELADO

            for item in conserto.pecas_usadas:
                peca_estoque = next(
                    (p for p in self.estoque if p.id == item.peca_id),
                    None,
                )
                if peca_estoque is None:
                    peca_estoque = next(
                        (
                            p for p in self.estoque
                            if p.nome.casefold() == item.nome.casefold()
                        ),
                        None,
                    )

                if peca_estoque is not None:
                    peca_estoque.quantidade += item.quantidade
                    peca_id_mov = peca_estoque.id
                    nome_peca_mov = peca_estoque.nome
                else:
                    # Caso a peça tenha sido excluída do estoque antes do cancelamento,
                    # recria o item no estoque para receber a devolução com consistência.
                    nova_peca = Peca(
                        id=item.peca_id,
                        nome=item.nome,
                        quantidade=item.quantidade,
                        preco_custo=item.preco_unitario,
                        preco_venda=item.preco_unitario,
                    )
                    self.estoque.append(nova_peca)
                    peca_id_mov = nova_peca.id
                    nome_peca_mov = nova_peca.nome

                self.movimentacoes.append(
                    MovimentacaoEstoque(
                        peca_id=peca_id_mov,
                        nome_peca=nome_peca_mov,
                        tipo="Entrada",
                        quantidade=item.quantidade,
                        motivo=f"Devolução por cancelamento do conserto #{conserto.id:04d}",
                        conserto_id=conserto.id,
                    )
                )

            if conserto.pecas_usadas:
                self.salvar("consertos", "estoque", "movimentacoes")
            else:
                self.salvar("consertos")

        return conserto

    def adicionar_comentario(
        self, conserto_id: int, mecanico: str, texto: str
    ) -> Conserto:
        """Registra uma observação no histórico do conserto ativo."""
        conserto = self.buscar_conserto_por_id(conserto_id)
        if conserto.situacao in (
            SituacaoConserto.CONCLUIDO,
            SituacaoConserto.CANCELADO,
        ):
            raise OperacaoNaoPermitida(
                "Não é possível comentar um conserto concluído ou cancelado."
            )
        mecanico = validar_texto(mecanico, "Mecânico")
        texto = validar_texto(texto, "Comentário")
        with self._transacao():
            conserto.comentarios.append(
                ComentarioMecanico(mecanico=mecanico, texto=texto)
            )
            self.salvar("consertos")
        return conserto

    def concluir_conserto(
        self, conserto_id: int, mao_de_obra: Decimal
    ) -> Conserto:
        """Finaliza um conserto ativo e registra o valor da mão de obra."""
        conserto = self.buscar_conserto_por_id(conserto_id)
        if conserto.situacao not in (
            SituacaoConserto.PENDENTE,
            SituacaoConserto.EM_EXECUCAO
        ):
            raise OperacaoNaoPermitida(
                "Este conserto não pode ser concluído."
            )
        valor_mao_de_obra = validar_dinheiro(mao_de_obra, "Mão de obra")
        with self._transacao():
            conserto.mao_de_obra = valor_mao_de_obra
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
        """Adiciona uma peça ao estoque ou soma unidades a uma peça existente."""
        nome = validar_texto(nome, "Nome da peça")
        quantidade = validar_inteiro_positivo(quantidade)
        custo = validar_dinheiro(preco_custo, "Preço de custo")
        venda = validar_dinheiro(
            custo if preco_venda is None else preco_venda,
            "Preço de venda"
        )
        with self._transacao():
            for peca in self.estoque:
                if peca.nome.casefold() == nome.casefold():
                    peca.quantidade += quantidade
                    peca.preco_custo = custo
                    peca.preco_venda = venda
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
            peca = Peca(self._proximo_id_peca, nome, quantidade, custo, venda)
            self.estoque.append(peca)
            self._proximo_id_peca += 1
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

    def editar_peca(
        self,
        peca_id: int,
        nome: str,
        quantidade: int,
        preco_custo: object,
        preco_venda: object,
    ) -> Peca:
        """
        Edita os dados de uma peça no cadastro do estoque e registra
        a movimentação no histórico com os valores anteriores e novos.
        Não altera os preços ou nomes de peças já registradas em consertos.
        """
        peca = self.buscar_peca_por_id(peca_id)
        nome_val = validar_texto(nome, "Nome da peça")
        qtd_val = validar_inteiro_nao_negativo(quantidade, "Quantidade em estoque")
        custo_val = validar_dinheiro(preco_custo, "Preço de custo")
        venda_val = validar_dinheiro(preco_venda, "Preço de venda")

        for outra in self.estoque:
            if outra.id != peca_id and outra.nome.casefold() == nome_val.casefold():
                raise DadoInvalido(
                    f"Já existe outra peça cadastrada com o nome '{outra.nome}'."
                )

        alteracoes = []
        if peca.nome != nome_val:
            alteracoes.append(f"Nome: '{peca.nome}' -> '{nome_val}'")
        if peca.quantidade != qtd_val:
            alteracoes.append(f"Qtd.: {peca.quantidade} -> {qtd_val}")
        if peca.preco_custo != custo_val:
            alteracoes.append(
                f"Custo: {formatar_moeda(peca.preco_custo)} -> {formatar_moeda(custo_val)}"
            )
        if peca.preco_venda != venda_val:
            alteracoes.append(
                f"Venda: {formatar_moeda(peca.preco_venda)} -> {formatar_moeda(venda_val)}"
            )

        if not alteracoes:
            return peca

        diferenca_qtd = abs(qtd_val - peca.quantidade)
        if qtd_val > peca.quantidade:
            tipo_mov = "Entrada"
        elif qtd_val < peca.quantidade:
            tipo_mov = "Saída"
        else:
            tipo_mov = "Edição"

        motivo = "Edição de cadastro no estoque (" + "; ".join(alteracoes) + ")"

        with self._transacao():
            peca.nome = nome_val
            peca.quantidade = qtd_val
            peca.preco_custo = custo_val
            peca.preco_venda = venda_val

            self.movimentacoes.append(
                MovimentacaoEstoque(
                    peca_id=peca.id,
                    nome_peca=peca.nome,
                    tipo=tipo_mov,
                    quantidade=diferenca_qtd,
                    motivo=motivo,
                )
            )
            self.salvar("estoque", "movimentacoes")
        return peca

    def excluir_peca(self, peca_id: int) -> Peca:
        """
        Remove uma peça do estoque e registra a exclusão (e eventual saída
        de saldo remanescente) no histórico de movimentações.
        Preserva intactos os registros de consertos anteriores e o histórico.
        """
        peca = self.buscar_peca_por_id(peca_id)
        qtd_remanescente = peca.quantidade
        motivo = (
            f"Exclusão de peça do estoque (ID #{peca.id} · "
            f"Custo: {formatar_moeda(peca.preco_custo)} · "
            f"Venda: {formatar_moeda(peca.preco_venda)}"
        )
        if qtd_remanescente > 0:
            motivo += f" · Baixa de {qtd_remanescente} un. em estoque)"
            tipo_mov = "Saída"
        else:
            motivo += " · Sem saldo em estoque)"
            tipo_mov = "Exclusão"

        with self._transacao():
            self.estoque.remove(peca)
            self.movimentacoes.append(
                MovimentacaoEstoque(
                    peca_id=peca.id,
                    nome_peca=peca.nome,
                    tipo=tipo_mov,
                    quantidade=qtd_remanescente,
                    motivo=motivo,
                )
            )
            self.salvar("estoque", "movimentacoes")
        return peca

    def usar_peca(
        self, conserto_id: int, peca_id: int, quantidade: int
    ) -> ItemUsado:
        """Registra a utilização de uma peça em um conserto ativo."""
        conserto = self.buscar_conserto_por_id(conserto_id)
        peca = self.buscar_peca_por_id(peca_id)
        quantidade = validar_inteiro_positivo(quantidade)
        if conserto.situacao not in (
            SituacaoConserto.PENDENTE,
            SituacaoConserto.EM_EXECUCAO
        ):
            raise OperacaoNaoPermitida(
                "Não é possível alterar as peças deste conserto."
            )
        if peca.quantidade < quantidade:
            raise OperacaoNaoPermitida(
                f"Estoque insuficiente. Quantidade disponível: {peca.quantidade}."
            )
        with self._transacao():
            item = ItemUsado(peca.id, peca.nome, quantidade, peca.preco_venda)
            peca.quantidade -= quantidade
            conserto.pecas_usadas.append(item)
            conserto.situacao = SituacaoConserto.EM_EXECUCAO
            self.movimentacoes.append(
                MovimentacaoEstoque(
                    peca.id,
                    peca.nome,
                    "Saída",
                    quantidade,
                    f"Utilização no conserto #{conserto.id:04d}",
                    conserto_id=conserto.id
                )
            )
            self.salvar("consertos", "estoque", "movimentacoes")
        return item

    def remover_peca_conserto(
        self, conserto_id: int, indice_item: int
    ) -> ItemUsado:
        """
        Remove uma peça utilizada de um conserto ativo e devolve
        sua quantidade ao estoque, registrando a entrada no histórico.
        """
        conserto = self.buscar_conserto_por_id(conserto_id)
        if conserto.situacao not in (
            SituacaoConserto.PENDENTE,
            SituacaoConserto.EM_EXECUCAO,
        ):
            raise OperacaoNaoPermitida(
                "Não é possível alterar as peças de um conserto concluído ou cancelado."
            )
        if indice_item < 0 or indice_item >= len(conserto.pecas_usadas):
            raise RegistroNaoEncontrado("Item de peça não encontrado neste conserto.")

        with self._transacao():
            item = conserto.pecas_usadas.pop(indice_item)

            peca_estoque = next(
                (p for p in self.estoque if p.id == item.peca_id),
                None,
            )
            if peca_estoque is None:
                peca_estoque = next(
                    (
                        p for p in self.estoque
                        if p.nome.casefold() == item.nome.casefold()
                    ),
                    None,
                )

            if peca_estoque is not None:
                peca_estoque.quantidade += item.quantidade
                peca_id_mov = peca_estoque.id
                nome_peca_mov = peca_estoque.nome
            else:
                nova_peca = Peca(
                    id=item.peca_id,
                    nome=item.nome,
                    quantidade=item.quantidade,
                    preco_custo=item.preco_unitario,
                    preco_venda=item.preco_unitario,
                )
                self.estoque.append(nova_peca)
                peca_id_mov = nova_peca.id
                nome_peca_mov = nova_peca.nome

            self.movimentacoes.append(
                MovimentacaoEstoque(
                    peca_id=peca_id_mov,
                    nome_peca=nome_peca_mov,
                    tipo="Entrada",
                    quantidade=item.quantidade,
                    motivo=f"Remoção de peça do conserto #{conserto.id:04d}",
                    conserto_id=conserto.id,
                )
            )
            self.salvar("consertos", "estoque", "movimentacoes")

        return item

    def calcular_valor_em_estoque(self) -> Decimal:
        """Calcula o valor total de custo das peças disponíveis."""
        return sum(
            (p.valor_em_estoque for p in self.estoque),
            Decimal("0.00")
        )

    def calcular_faturamento(self) -> Decimal:
        """Calcula o faturamento dos consertos concluídos."""
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
    """Cria e configura a aplicação Flask."""
    app = Flask(
        __name__,
        template_folder=str(TEMPLATE_DIR),
        static_folder=str(STATIC_DIR),
    )
    app.secret_key = os.environ.get("FLASK_SECRET_KEY", "oficina-dev-key")
    oficina = Oficina(PASTA_DADOS)

    # -----------------------------------------------------------------------
    # PÁGINA INICIAL
    # -----------------------------------------------------------------------
    @app.route("/")
    def index():
        """Exibe o painel principal com os indicadores da oficina."""
        consertos = oficina.listar_consertos()
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
            "faturamento": formatar_moeda(oficina.calcular_faturamento()),
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
        """Exibe o formulário e processa novos cadastros."""
        if request.method == "POST":
            cliente = request.form.get("cliente", "")
            veiculo = request.form.get("veiculo", "")
            mecanico = request.form.get("mecanico", "")
            problema_sel = request.form.get("problema", "").strip()
            problema_outro = request.form.get("problema_outro", "")
            problema = problema_outro if problema_sel == "outro" else problema_sel
            try:
                conserto = oficina.cadastrar_conserto(
                    cliente, veiculo, problema, mecanico
                )
                flash(
                    f"Conserto #{conserto.id:04d} cadastrado com sucesso.",
                    "sucesso"
                )
                return redirect(
                    url_for("detalhe_conserto", conserto_id=conserto.id)
                )
            except ErroOficina as erro:
                flash(str(erro), "erro")
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
        return render_template("cadastrar.html", problemas=PROBLEMAS_COMUNS)

    # -----------------------------------------------------------------------
    # LISTAGEM E PESQUISA DE CONSERTOS
    # -----------------------------------------------------------------------
    @app.route("/consertos")
    def listar_consertos():
        """Exibe os consertos e permite pesquisar e filtrar os registros."""
        termo = request.args.get("q", "").strip()
        situacao_filtro = request.args.get("situacao", "").strip()
        try:
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
            flash(str(erro), "erro")
            consertos = oficina.listar_consertos()
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
    @app.route("/consertos/<int:conserto_id>", methods=["GET", "POST"])
    def detalhe_conserto(conserto_id: int):
        """Exibe os detalhes de um atendimento e processa suas operações."""
        try:
            conserto = oficina.buscar_conserto_por_id(conserto_id)
        except RegistroNaoEncontrado as erro:
            flash(str(erro), "erro")
            return redirect(url_for("listar_consertos"))

        if request.method == "POST":
            acao = request.form.get("acao", "").strip()
            try:
                if acao == "usar_peca":
                    peca_id = int(request.form.get("peca", "0"))
                    quantidade = int(request.form.get("quantidade", "0"))
                    item = oficina.usar_peca(conserto_id, peca_id, quantidade)
                    flash(
                        f"Peça registrada: {item.nome} x{item.quantidade} "
                        f"({formatar_moeda(item.subtotal)}).",
                        "sucesso",
                    )
                elif acao == "remover_peca":
                    indice_item = int(request.form.get("indice_item", "-1"))
                    item_removido = oficina.remover_peca_conserto(
                        conserto_id, indice_item
                    )
                    flash(
                        f"Peça '{item_removido.nome}' (x{item_removido.quantidade}) "
                        "removida do conserto e devolvida ao estoque.",
                        "sucesso",
                    )
                elif acao == "comentar":
                    texto = request.form.get("comentario", "")
                    oficina.adicionar_comentario(
                        conserto_id, conserto.mecanico, texto
                    )
                    flash("Comentário salvo.", "sucesso")
                elif acao == "manter":
                    if conserto.situacao in (
                        SituacaoConserto.CONCLUIDO,
                        SituacaoConserto.CANCELADO,
                    ):
                        flash(
                            "Um conserto concluído ou cancelado não pode ser "
                            "mantido em execução.",
                            "erro",
                        )
                    else:
                        if conserto.situacao == SituacaoConserto.PENDENTE:
                            oficina.iniciar_conserto(conserto_id)
                        flash("Conserto mantido em execução.", "sucesso")
                elif acao == "concluir":
                    texto_mao_de_obra = request.form.get("mao_de_obra", "").strip()
                    if not texto_mao_de_obra:
                        raise DadoInvalido(
                            "Informe o valor da mão de obra para concluir o conserto."
                        )
                    mao_de_obra = validar_dinheiro(texto_mao_de_obra, "Mão de obra")
                    oficina.concluir_conserto(conserto_id, mao_de_obra)
                    flash("Conserto concluído com sucesso.", "sucesso")
                elif acao == "cancelar":
                    qtd_itens = len(conserto.pecas_usadas)
                    oficina.cancelar_conserto(conserto_id)
                    if qtd_itens > 0:
                        flash(
                            f"Conserto #{conserto.id:04d} cancelado e peças devolvidas ao estoque.",
                            "sucesso",
                        )
                    else:
                        flash(
                            f"Conserto #{conserto.id:04d} cancelado com sucesso.",
                            "sucesso",
                        )
                else:
                    flash("Ação inválida.", "erro")
            except ValueError:
                flash("Informe valores numéricos válidos.", "erro")
            except ErroOficina as erro:
                flash(str(erro), "erro")

            return redirect(
                url_for("detalhe_conserto", conserto_id=conserto_id)
            )

        return render_template(
            "detalhe.html",
            conserto=conserto,
            estoque=oficina.estoque,
            formatar_moeda=formatar_moeda,
        )

    # -----------------------------------------------------------------------
    # EDIÇÃO DE CONSERTO
    # -----------------------------------------------------------------------
    @app.route("/consertos/<int:conserto_id>/editar", methods=["GET", "POST"])
    def editar_conserto(conserto_id: int):
        """Exibe o formulário e processa a edição de um conserto ativo."""
        try:
            conserto = oficina.buscar_conserto_por_id(conserto_id)
        except RegistroNaoEncontrado as erro:
            flash(str(erro), "erro")
            return redirect(url_for("listar_consertos"))

        if conserto.situacao in (
            SituacaoConserto.CONCLUIDO,
            SituacaoConserto.CANCELADO,
        ):
            flash(
                "Não é possível editar um conserto concluído ou cancelado.",
                "erro",
            )
            return redirect(url_for("detalhe_conserto", conserto_id=conserto_id))

        if request.method == "POST":
            cliente = request.form.get("cliente", "")
            veiculo = request.form.get("veiculo", "")
            mecanico = request.form.get("mecanico", "")
            problema = request.form.get("problema", "")
            mao_de_obra = request.form.get("mao_de_obra", "")
            try:
                oficina.editar_conserto(
                    conserto_id=conserto_id,
                    cliente=cliente,
                    veiculo=veiculo,
                    mecanico=mecanico,
                    problema=problema,
                    mao_de_obra=mao_de_obra,
                )
                flash(
                    f"Conserto #{conserto.id:04d} atualizado com sucesso.",
                    "sucesso",
                )
                return redirect(
                    url_for("detalhe_conserto", conserto_id=conserto_id)
                )
            except ErroOficina as erro:
                flash(str(erro), "erro")
                return render_template(
                    "editar_conserto.html",
                    conserto=conserto,
                    form_dados={
                        "cliente": cliente,
                        "veiculo": veiculo,
                        "mecanico": mecanico,
                        "problema": problema,
                        "mao_de_obra": mao_de_obra,
                    },
                )

        return render_template(
            "editar_conserto.html",
            conserto=conserto,
            form_dados={
                "cliente": conserto.cliente,
                "veiculo": conserto.veiculo,
                "mecanico": conserto.mecanico,
                "problema": conserto.problema,
                "mao_de_obra": formatar_decimal_input(conserto.mao_de_obra),
            },
        )

    # -----------------------------------------------------------------------
    # GERENCIAMENTO DO ESTOQUE
    # -----------------------------------------------------------------------
    @app.route("/estoque", methods=["GET", "POST"])
    def estoque():
        """
        Exibe o estoque e processa entrada, edição inline e exclusão de peças.
        """
        edicao_erro = None

        if request.method == "POST":
            acao = request.form.get("acao", "adicionar").strip()

            if acao == "editar_peca":
                peca_id_str = request.form.get("peca_id", "0")
                nome = request.form.get("nome", "")
                qtd_str = request.form.get("quantidade", "")
                custo_str = request.form.get("custo", "")
                venda_str = request.form.get("venda", "")
                erros_campos = {}

                try:
                    peca_id = int(peca_id_str)
                except ValueError:
                    flash("Identificador de peça inválido.", "erro")
                    return redirect(url_for("estoque"))

                if not nome.strip():
                    erros_campos["nome"] = "Nome da peça é obrigatório."

                quantidade = None
                try:
                    if not qtd_str.strip() or "." in qtd_str or "," in qtd_str:
                        raise ValueError()
                    quantidade = validar_inteiro_nao_negativo(
                        int(qtd_str.strip()), "Quantidade"
                    )
                except (ValueError, DadoInvalido):
                    erros_campos["quantidade"] = "Informe um inteiro >= 0."

                custo = None
                try:
                    custo = validar_dinheiro(custo_str, "Preço de custo")
                except DadoInvalido as e:
                    erros_campos["custo"] = str(e)

                venda = None
                try:
                    venda = validar_dinheiro(venda_str, "Preço de venda")
                except DadoInvalido as e:
                    erros_campos["venda"] = str(e)

                if not erros_campos:
                    try:
                        peca = oficina.editar_peca(
                            peca_id, nome, quantidade, custo, venda
                        )
                        flash(
                            f"Peça '{peca.nome}' atualizada com sucesso.",
                            "sucesso",
                        )
                        return redirect(url_for("estoque"))
                    except DadoInvalido as erro:
                        erros_campos["nome"] = str(erro)
                    except ErroOficina as erro:
                        flash(str(erro), "erro")
                        return redirect(url_for("estoque"))

                flash("Corrija os campos destacados na edição da peça.", "erro")
                edicao_erro = {
                    "peca_id": peca_id,
                    "nome": nome,
                    "quantidade": qtd_str,
                    "custo": custo_str,
                    "venda": venda_str,
                    "erros": erros_campos,
                }

            elif acao == "excluir_peca":
                try:
                    peca_id = int(request.form.get("peca_id", "0"))
                    peca_removida = oficina.excluir_peca(peca_id)
                    flash(
                        f"Peça '{peca_removida.nome}' excluída do estoque.",
                        "sucesso",
                    )
                except ValueError:
                    flash("Identificador de peça inválido.", "erro")
                except ErroOficina as erro:
                    flash(str(erro), "erro")
                return redirect(url_for("estoque"))

            else:
                nome = request.form.get("nome", "")
                try:
                    quantidade = int(request.form.get("quantidade", "0"))
                    custo = validar_dinheiro(
                        request.form.get("custo", ""), "Preço de custo"
                    )
                    venda = validar_dinheiro(
                        request.form.get("venda", ""), "Preço de venda"
                    )
                    peca = oficina.adicionar_peca(nome, quantidade, custo, venda)
                    flash(
                        f"Estoque atualizado: {peca.nome} "
                        f"({peca.quantidade} un.).",
                        "sucesso",
                    )
                    return redirect(url_for("estoque"))
                except ValueError:
                    flash("Quantidade deve ser um número inteiro válido.", "erro")
                except ErroOficina as erro:
                    flash(str(erro), "erro")

        return render_template(
            "estoque.html",
            pecas=oficina.estoque,
            valor_estoque=formatar_moeda(oficina.calcular_valor_em_estoque()),
            formatar_moeda=formatar_moeda,
            formatar_decimal_input=formatar_decimal_input,
            edicao_erro=edicao_erro,
        )

    # -----------------------------------------------------------------------
    # HISTÓRICO DE MOVIMENTAÇÕES
    # -----------------------------------------------------------------------
    @app.route("/historico")
    def historico():
        """Exibe as movimentações do estoque da mais recente para a mais antiga."""
        movimentacoes = list(reversed(oficina.movimentacoes))
        return render_template("historico.html", movimentacoes=movimentacoes)

    return app


# ---------------------------------------------------------------------------
# INICIALIZAÇÃO DA APLICAÇÃO
# ---------------------------------------------------------------------------
app = criar_app()

if __name__ == "__main__":
    app.run(debug=True, use_reloader=False)