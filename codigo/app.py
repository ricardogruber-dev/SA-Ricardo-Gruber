"""
Sistema de oficina mecânica - Python puro e terminal.
Os dados são mantidos em memória e são perdidos ao encerrar o programa.
"""
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from enum import Enum
import os

LARGURA = 72
CENTAVO = Decimal("0.01")


# ---------------------------------------------------------------------------
# Exceções específicas
# ---------------------------------------------------------------------------

class ErroOficina(Exception):
    """Erro esperado nas operações do sistema."""


class DadoInvalido(ErroOficina):
    """Representa um dado informado pelo usuário que não passou na validação."""
    pass


class RegistroNaoEncontrado(ErroOficina):
    """Indica que um concerto ou uma peça não foi localizado."""
    pass


class OperacaoNaoPermitida(ErroOficina):
    """Indica que uma ação não é válida para o estado atual do registro."""
    pass


# ---------------------------------------------------------------------------
# Validações e formatação
# ---------------------------------------------------------------------------

def validar_texto(valor: str, campo: str) -> str:
    """Valida um texto obrigatório e remove espaços extras das extremidades."""
    if not isinstance(valor, str) or not valor.strip():
        raise DadoInvalido(f"{campo} é obrigatório.")
    return valor.strip()


def validar_inteiro_positivo(valor: int, campo: str = "Quantidade") -> int:
    """Garante que a quantidade seja um número inteiro maior que zero."""
    if isinstance(valor, bool) or not isinstance(valor, int) or valor <= 0:
        raise DadoInvalido(f"{campo} deve ser um inteiro maior que zero.")
    return valor


def validar_dinheiro(
    valor: object, campo: str = "Valor", permitir_zero: bool = True
) -> Decimal:
    """Valida um valor monetário com Decimal para evitar imprecisão de float."""
    try:
        numero = Decimal(str(valor).strip().replace(",", "."))
    except (InvalidOperation, ValueError, AttributeError):
        raise DadoInvalido(f"{campo} inválido.")

    if not numero.is_finite():
        raise DadoInvalido(f"{campo} deve ser um número finito.")
    if numero < 0 or (not permitir_zero and numero == 0):
        regra = "maior que zero" if not permitir_zero else "não negativo"
        raise DadoInvalido(f"{campo} deve ser {regra}.")
    # A quantização também pode falhar quando o número tem dígitos demais.
    # Transformamos esse caso em um erro de validação, em vez de deixar
    # uma exceção interna do Decimal interromper o programa.
    try:
        return numero.quantize(CENTAVO, rounding=ROUND_HALF_UP)
    except InvalidOperation:
        raise DadoInvalido(f"{campo} inválido ou fora do limite aceito.") from None


def formatar_moeda(valor: Decimal) -> str:
    """Converte um valor Decimal para o formato monetário brasileiro."""
    texto = f"{Decimal(valor):,.2f}"
    return "R$ " + texto.replace(",", "X").replace(".", ",").replace("X", ".")


def imprimir_linha(caractere: str = "-") -> None:
    """Imprime uma linha usada para organizar visualmente as telas."""
    print(caractere * LARGURA)


def imprimir_titulo(texto: str) -> None:
    """Exibe um título padronizado para a tela atual."""
    print()
    imprimir_linha("=")
    print(texto.upper().center(LARGURA))
    imprimir_linha("=")


def pausar() -> None:
    """Aguarda ENTER para que o usuário consiga ler o resultado da operação."""
    input("\nPressione ENTER para continuar...")


def limpar_terminal() -> None:
    """Limpa a tela do terminal no Windows, Linux ou macOS."""
    comando = "cls" if os.name == "nt" else "clear"
    os.system(comando)


# ---------------------------------------------------------------------------
# Modelos
# ---------------------------------------------------------------------------

class SituacaoConcerto(Enum):
    """Define os estados possíveis de um concerto durante seu atendimento."""
    PENDENTE = "Pendente"
    EM_EXECUCAO = "Em execução"
    CONCLUIDO = "Concluído"


@dataclass
class Peca:
    """Armazena os dados de uma peça e sua quantidade disponível no estoque."""
    id: int
    nome: str
    quantidade: int
    preco_custo: Decimal
    preco_venda: Decimal

    @property
    def valor_em_estoque(self) -> Decimal:
        """Calcula quanto custaram as unidades desta peça que ainda estão no estoque."""
        return self.preco_custo * self.quantidade


@dataclass
class ItemUsado:
    """Registra uma peça aplicada em um concerto e o preço considerado na utilização."""
    peca_id: int
    nome: str
    quantidade: int
    preco_unitario: Decimal

    @property
    def subtotal(self) -> Decimal:
        """Calcula o custo total deste item pela quantidade utilizada."""
        return self.preco_unitario * self.quantidade


@dataclass
class ComentarioMecanico:
    """Guarda uma observação do mecânico, seu autor e a data do registro."""
    mecanico: str
    texto: str
    data: datetime = field(default_factory=datetime.now)


@dataclass
class Concerto:
    """Representa o atendimento de um veículo, desde o cadastro até a conclusão."""
    id: int
    cliente: str
    veiculo: str
    problema: str
    mecanico: str
    data_entrada: datetime = field(default_factory=datetime.now)
    pecas_usadas: list[ItemUsado] = field(default_factory=list)
    mao_de_obra: Decimal = Decimal("0.00")
    situacao: SituacaoConcerto = SituacaoConcerto.PENDENTE
    data_conclusao: datetime | None = None
    comentarios: list[ComentarioMecanico] = field(default_factory=list)

    @property
    def total_pecas(self) -> Decimal:
        """Soma os subtotais de todas as peças utilizadas no concerto."""
        return sum((item.subtotal for item in self.pecas_usadas), Decimal("0.00"))

    @property
    def total(self) -> Decimal:
        """Soma o valor das peças e da mão de obra do concerto."""
        return self.total_pecas + self.mao_de_obra


@dataclass
class MovimentacaoEstoque:
    """Registra uma entrada ou saída de peças para manter o histórico do estoque."""
    peca_id: int
    nome_peca: str
    tipo: str
    quantidade: int
    motivo: str
    data: datetime = field(default_factory=datetime.now)
    concerto_id: int | None = None


# ---------------------------------------------------------------------------
# Regras de negócio
# ---------------------------------------------------------------------------

class Oficina:
    """Centraliza os registros e as regras de negócio da oficina."""
    def __init__(self) -> None:
        """Prepara as listas de dados e os contadores de identificadores."""
        self.concertos: list[Concerto] = []
        self.estoque: list[Peca] = []
        self.movimentacoes: list[MovimentacaoEstoque] = []
        self._proximo_id_concerto = 1
        self._proximo_id_peca = 1

    def buscar_concerto_por_id(self, concerto_id: int) -> Concerto:
        """Localiza um concerto pelo identificador ou informa que ele não existe."""
        for concerto in self.concertos:
            if concerto.id == concerto_id:
                return concerto
        raise RegistroNaoEncontrado("Concerto não encontrado.")

    def buscar_peca_por_id(self, peca_id: int) -> Peca:
        """Localiza uma peça pelo identificador ou informa que ela não existe."""
        for peca in self.estoque:
            if peca.id == peca_id:
                return peca
        raise RegistroNaoEncontrado("Peça não encontrada.")

    def buscar_concertos_por_texto(self, texto: str) -> list[Concerto]:
        """Busca o termo no cliente, veículo, mecânico ou problema dos concertos."""
        termo = validar_texto(texto, "Busca").casefold()
        return [
            c for c in self.concertos
            if termo in c.cliente.casefold()
            or termo in c.veiculo.casefold()
            or termo in c.mecanico.casefold()
            or termo in c.problema.casefold()
        ]

    def cadastrar_concerto(
        self, cliente: str, veiculo: str, problema: str, mecanico: str
    ) -> Concerto:
        """Valida os dados, cria um concerto pendente e o adiciona à oficina."""
        dados = (
            validar_texto(cliente, "Cliente"),
            validar_texto(veiculo, "Veículo"),
            validar_texto(problema, "Problema"),
            validar_texto(mecanico, "Mecânico"),
        )
        concerto = Concerto(self._proximo_id_concerto, *dados)
        self.concertos.append(concerto)
        self._proximo_id_concerto += 1
        return concerto

    def listar_concertos(
        self, situacao: SituacaoConcerto | None = None
    ) -> list[Concerto]:
        """Retorna todos os concertos ou somente os que têm uma situação específica."""
        if situacao is None:
            return list(self.concertos)
        return [c for c in self.concertos if c.situacao == situacao]

    def iniciar_concerto(self, concerto_id: int) -> Concerto:
        """Muda um concerto pendente para em execução."""
        concerto = self.buscar_concerto_por_id(concerto_id)
        if concerto.situacao != SituacaoConcerto.PENDENTE:
            raise OperacaoNaoPermitida(
                "Somente um concerto pendente pode ser iniciado."
            )
        concerto.situacao = SituacaoConcerto.EM_EXECUCAO
        return concerto

    def adicionar_comentario(
        self, concerto_id: int, mecanico: str, texto: str
    ) -> Concerto:
        """Registra uma observação do mecânico em um concerto ainda não concluído."""
        concerto = self.buscar_concerto_por_id(concerto_id)
        if concerto.situacao == SituacaoConcerto.CONCLUIDO:
            raise OperacaoNaoPermitida(
                "Não é possível comentar um concerto concluído."
            )
        mecanico = validar_texto(mecanico, "Mecânico")
        texto = validar_texto(texto, "Comentário")
        concerto.comentarios.append(
            ComentarioMecanico(mecanico=mecanico, texto=texto)
        )
        return concerto

    def concluir_concerto(self, concerto_id: int, mao_de_obra: Decimal) -> Concerto:
        """Valida a mão de obra e marca o concerto como concluído."""
        concerto = self.buscar_concerto_por_id(concerto_id)
        if concerto.situacao not in (
            SituacaoConcerto.PENDENTE, SituacaoConcerto.EM_EXECUCAO
        ):
            raise OperacaoNaoPermitida("Este concerto não pode ser concluído.")
        concerto.mao_de_obra = validar_dinheiro(mao_de_obra, "Mão de obra")
        concerto.situacao = SituacaoConcerto.CONCLUIDO
        concerto.data_conclusao = datetime.now()
        return concerto

    def adicionar_peca(
        self,
        nome: str,
        quantidade: int,
        preco_custo: Decimal,
        preco_venda: Decimal | None = None,
    ) -> Peca:
        """Cadastra uma peça ou soma unidades quando ela já existe no estoque."""
        nome = validar_texto(nome, "Nome da peça")
        quantidade = validar_inteiro_positivo(quantidade)
        custo = validar_dinheiro(preco_custo, "Preço de custo")
        venda = validar_dinheiro(
            custo if preco_venda is None else preco_venda, "Preço de venda"
        )

        for peca in self.estoque:
            if peca.nome.casefold() == nome.casefold():
                peca.quantidade += quantidade
                peca.preco_custo = custo
                peca.preco_venda = venda
                self.movimentacoes.append(MovimentacaoEstoque(
                    peca.id, peca.nome, "Entrada", quantidade, "Reposição de estoque"
                ))
                return peca

        peca = Peca(self._proximo_id_peca, nome, quantidade, custo, venda)
        self.estoque.append(peca)
        self._proximo_id_peca += 1
        self.movimentacoes.append(MovimentacaoEstoque(
            peca.id, peca.nome, "Entrada", quantidade, "Cadastro inicial"
        ))
        return peca

    def usar_peca(
        self, concerto_id: int, peca_id: int, quantidade: int
    ) -> ItemUsado:
        """Registra a peça no concerto e atualiza a quantidade disponível."""
        concerto = self.buscar_concerto_por_id(concerto_id)
        peca = self.buscar_peca_por_id(peca_id)
        quantidade = validar_inteiro_positivo(quantidade)

        if concerto.situacao not in (
            SituacaoConcerto.PENDENTE, SituacaoConcerto.EM_EXECUCAO
        ):
            raise OperacaoNaoPermitida(
                "Não é possível alterar as peças deste concerto."
            )
        if peca.quantidade < quantidade:
            raise OperacaoNaoPermitida(
                f"Estoque insuficiente. Quantidade disponível: {peca.quantidade}."
            )

        item = ItemUsado(peca.id, peca.nome, quantidade, peca.preco_venda)
        peca.quantidade -= quantidade
        concerto.pecas_usadas.append(item)
        concerto.situacao = SituacaoConcerto.EM_EXECUCAO
        self.movimentacoes.append(MovimentacaoEstoque(
            peca.id, peca.nome, "Saída", quantidade,
            f"Utilização no concerto #{concerto.id}", concerto_id=concerto.id
        ))
        return item

    def calcular_valor_em_estoque(self) -> Decimal:
        """Soma o valor de custo de todas as peças disponíveis no estoque."""
        return sum((p.valor_em_estoque for p in self.estoque), Decimal("0.00"))

    def calcular_faturamento(self) -> Decimal:
        """Soma os totais dos concertos que já foram concluídos."""
        return sum(
            (c.total for c in self.concertos
             if c.situacao == SituacaoConcerto.CONCLUIDO),
            Decimal("0.00")
        )


# ---------------------------------------------------------------------------
# Entrada de dados
# ---------------------------------------------------------------------------

def ler_texto(pergunta: str) -> str:
    """Solicita um texto obrigatório e repete a pergunta enquanto estiver vazio."""
    while True:
        valor = input(pergunta).strip()
        if valor:
            return valor
        print("Este campo é obrigatório.")


def ler_inteiro(pergunta: str) -> int:
    """Solicita uma quantidade inteira positiva e trata entradas inválidas."""
    while True:
        try:
            valor = int(input(pergunta).strip())
            return validar_inteiro_positivo(valor)
        except ValueError:
            print("Digite um número inteiro válido.")
        except DadoInvalido as erro:
            print(erro)


def ler_dinheiro(pergunta: str) -> Decimal:
    """Solicita um valor monetário e repete a pergunta se o valor for inválido."""
    while True:
        try:
            return validar_dinheiro(input(pergunta), "Valor")
        except DadoInvalido as erro:
            print(erro)


# ---------------------------------------------------------------------------
# Telas
# ---------------------------------------------------------------------------

def mostrar_concerto(c: Concerto) -> None:
    """Exibe dados, problema, peças, comentários e valores do concerto."""
    imprimir_linha()
    print(f"#{c.id:04d} | {c.situacao.value}")
    print(f"Cliente:  {c.cliente}")
    print(f"Veículo:  {c.veiculo}")
    print(f"Mecânico: {c.mecanico}")
    print(f"Entrada:  {c.data_entrada:%d/%m/%Y %H:%M}")
    print(f"Problema: {c.problema}")
    if c.pecas_usadas:
        print("Peças utilizadas:")
        for item in c.pecas_usadas:
            print(
                f"  {item.nome} x{item.quantidade} | "
                f"{formatar_moeda(item.subtotal)}"
            )
    if c.comentarios:
        print("Comentários do mecânico:")
        for comentario in c.comentarios:
            data = comentario.data.strftime("%d/%m/%Y %H:%M")
            print(f"  [{data}] {comentario.mecanico}: {comentario.texto}")
    if c.situacao == SituacaoConcerto.CONCLUIDO:
        print(f"Mão de obra: {formatar_moeda(c.mao_de_obra)}")
        print(f"TOTAL:       {formatar_moeda(c.total)}")


def mostrar_estoque(oficina: Oficina) -> None:
    """Mostra todas as peças cadastradas e suas quantidades e preços."""
    if not oficina.estoque:
        print("Estoque vazio.")
        return
    print(f"{'ID':<5}{'PEÇA':<27}{'QTD':>6}{'CUSTO':>16}{'VENDA':>16}")
    imprimir_linha()
    for p in oficina.estoque:
        print(
            f"{p.id:<5}{p.nome[:25]:<27}{p.quantidade:>6}"
            f"{formatar_moeda(p.preco_custo):>16}"
            f"{formatar_moeda(p.preco_venda):>16}"
        )


def selecionar_problema() -> str:
    """Mostra problemas comuns ou permite que o usuário descreva outro."""
    problemas_comuns = {
        "1": "Motor não liga",
        "2": "Motor falhando ou perdendo potência",
        "3": "Superaquecimento do motor",
        "4": "Barulho ou problema na suspensão",
        "5": "Problema nos freios",
        "6": "Embreagem com defeito",
        "7": "Dificuldade para trocar as marchas",
        "8": "Bateria descarregando ou não dando partida",
        "9": "Vazamento de óleo ou outro fluido",
        "10": "Problema elétrico ou nas luzes",
    }

    imprimir_titulo("Qual problema o veículo apresenta?")
    for numero, descricao in problemas_comuns.items():
        print(f"  {numero:>2} - {descricao}")
    print("   0 - Outro problema (digitar descrição)")

    while True:
        opcao = input("\nEscolha uma opção: ").strip()
        if opcao in problemas_comuns:
            problema = problemas_comuns[opcao]
            print(f"Problema selecionado: {problema}")
            return problema
        if opcao == "0":
            return ler_texto("Descreva o problema apresentado: ")
        print("Opção inválida. Escolha de 1 a 10 ou 0 para descrever outro problema.")


def tela_cadastrar_concerto(oficina: Oficina) -> None:
    """Conduz o usuário pelo cadastro de um novo concerto."""
    imprimir_titulo("Cadastrar concerto")
    cliente = ler_texto("Cliente: ")
    veiculo = ler_texto("Veículo (modelo/placa): ")
    problema = selecionar_problema()
    mecanico = ler_texto("Mecânico responsável: ")

    c = oficina.cadastrar_concerto(cliente, veiculo, problema, mecanico)
    print(f"\nConcerto #{c.id} cadastrado com sucesso.")


def tela_listar_concertos(oficina: Oficina) -> None:
    """Exibe todos os concertos cadastrados."""
    imprimir_titulo("Concertos")
    if not oficina.concertos:
        print("Nenhum concerto cadastrado.")
        return
    for c in oficina.listar_concertos():
        mostrar_concerto(c)


def tela_buscar_concerto(oficina: Oficina) -> None:
    """Solicita um termo e mostra os concertos correspondentes."""
    imprimir_titulo("Buscar concerto")
    resultados = oficina.buscar_concertos_por_texto(
        ler_texto("Buscar por cliente, veículo, mecânico ou problema: ")
    )
    if not resultados:
        print("Nenhum concerto encontrado.")
        return
    for c in resultados:
        mostrar_concerto(c)


def tela_adicionar_peca(oficina: Oficina) -> None:
    """Solicita os dados de uma peça e atualiza o estoque."""
    imprimir_titulo("Adicionar peça ao estoque")
    p = oficina.adicionar_peca(
        ler_texto("Nome da peça: "),
        ler_inteiro("Quantidade: "),
        ler_dinheiro("Preço de custo unitário (R$): "),
        ler_dinheiro("Preço de venda unitário (R$): "),
    )
    print(f"\nEstoque atualizado: {p.nome} ({p.quantidade} unidade(s)).")


def tela_concluir_concerto(oficina: Oficina) -> None:
    """Registra peças e comentário e define a ação para o concerto."""
    imprimir_titulo("Realizar concerto")
    abertos = (
        oficina.listar_concertos(SituacaoConcerto.PENDENTE)
        + oficina.listar_concertos(SituacaoConcerto.EM_EXECUCAO)
    )
    if not abertos:
        print("Não há concertos pendentes ou em execução.")
        return

    for c in abertos:
        print(f"#{c.id} - {c.cliente} - {c.veiculo} ({c.situacao.value})")

    concerto_id = ler_inteiro("\nNúmero do concerto: ")
    concerto = oficina.buscar_concerto_por_id(concerto_id)
    if concerto.situacao == SituacaoConcerto.CONCLUIDO:
        print("Este concerto já está concluído.")
        return

    # Mostra o problema registrado antes de solicitar peças ou comentários.
    imprimir_titulo("Problema informado no cadastro")
    print(f"Cliente:  {concerto.cliente}")
    print(f"Veículo:  {concerto.veiculo}")
    print(f"Problema: {concerto.problema}")
    print(f"Situação: {concerto.situacao.value}")
    imprimir_linha()

    # Primeiro guardamos as escolhas em variáveis locais. Só aplicamos as
    # alterações ao estoque e ao concerto depois da decisão final do mecânico.
    # Isso evita descontar peças ou salvar comentários se ele cancelar.
    peca_selecionada: Peca | None = None
    quantidade_selecionada = 0

    print("\nInforme a peça que será utilizada. Deixe vazio se não precisar de peça.")
    nome_peca = input("Nome da peça: ").strip()
    if nome_peca:
        peca = next(
            (p for p in oficina.estoque if p.nome.casefold() == nome_peca.casefold()),
            None,
        )
        if peca is None or peca.quantidade <= 0:
            print(f"\nNão temos '{nome_peca}' disponível no estoque.")
            decisao = input(
                "Digite S para continuar sem essa peça; "
                "qualquer outra tecla cancela esta operação: "
            ).strip().casefold()
            if decisao != "s":
                print("Operação cancelada. Voltando ao menu.")
                return
        else:
            print(f"Disponível: {peca.quantidade} unidade(s).")
            quantidade = ler_inteiro("Quantidade utilizada: ")
            if peca.quantidade < quantidade:
                print(
                    f"\nEstoque insuficiente. Há somente {peca.quantidade} "
                    "unidade(s) disponível(is)."
                )
                decisao = input(
                    "Digite S para continuar sem essa peça; "
                    "qualquer outra tecla cancela esta operação: "
                ).strip().casefold()
                if decisao != "s":
                    print("Operação cancelada. Voltando ao menu.")
                    return
            else:
                peca_selecionada = peca
                quantidade_selecionada = quantidade

    print("\nComentário do mecânico (ENTER para deixar em branco):")
    comentario = input("Comentário: ").strip()

    print("\nO que deseja fazer com este concerto?")
    print("  1 - Concluir concerto")
    print("  2 - Deixar em execução")
    print("  0 - Cancelar e voltar ao menu")
    while True:
        acao = input("Escolha uma opção: ").strip()
        if acao in {"0", "1", "2"}:
            break
        print("Opção inválida. Digite 1, 2 ou 0.")

    if acao == "0":
        print("Operação cancelada. Nenhuma peça ou comentário foi registrado.")
        return

    mao_de_obra: Decimal | None = None
    if acao == "1":
        mao_de_obra = ler_dinheiro("Valor da mão de obra (R$): ")

    # Confirma as alterações somente depois da escolha final.
    if peca_selecionada is not None:
        item = oficina.usar_peca(
            concerto_id, peca_selecionada.id, quantidade_selecionada
        )
        print(
            f"Peça registrada: {item.nome} x{item.quantidade} "
            f"({formatar_moeda(item.subtotal)})."
        )

    if comentario:
        oficina.adicionar_comentario(concerto_id, concerto.mecanico, comentario)

    if acao == "1":
        # O valor é preenchido acima sempre que a opção de concluir é escolhida.
        assert mao_de_obra is not None
        concerto = oficina.concluir_concerto(concerto_id, mao_de_obra)
        print("\nConcerto concluído com sucesso!")
    else:
        if concerto.situacao == SituacaoConcerto.PENDENTE:
            oficina.iniciar_concerto(concerto_id)
        concerto = oficina.buscar_concerto_por_id(concerto_id)
        print("\nConcerto mantido em execução.")

    mostrar_concerto(concerto)


def tela_historico_estoque(oficina: Oficina) -> None:
    """Exibe as movimentações de entrada e saída de peças."""
    imprimir_titulo("Histórico do estoque")
    if not oficina.movimentacoes:
        print("Nenhuma movimentação registrada.")
        return
    for m in reversed(oficina.movimentacoes):
        print(
            f"{m.data:%d/%m/%Y %H:%M} | {m.tipo:<7} | {m.nome_peca} | "
            f"{m.quantidade} un. | {m.motivo}"
        )


def tela_resumo(oficina: Oficina) -> None:
    """Apresenta quantidades por situação, faturamento e valor do estoque."""
    imprimir_titulo("Resumo da oficina")
    print(f"Concertos cadastrados: {len(oficina.concertos)}")
    for situacao in SituacaoConcerto:
        print(
            f"{situacao.value + ':':<23}"
            f"{len(oficina.listar_concertos(situacao))}"
        )
    imprimir_linha()
    print(f"Faturamento concluído: {formatar_moeda(oficina.calcular_faturamento())}")
    valor_estoque = oficina.calcular_valor_em_estoque()
    print(f"Valor em estoque:      {formatar_moeda(valor_estoque)}")


def mostrar_menu() -> None:
    """Exibe as opções disponíveis no menu principal."""
    imprimir_titulo("Sistema de oficina mecânica")
    opcoes = {
        "1": "Cadastrar concerto",
        "2": "Listar concertos",
        "3": "Buscar concerto",
        "4": "Adicionar peça ao estoque",
        "5": "Ver estoque",
        "6": "Realizar / acompanhar concerto",
        "7": "Resumo da oficina",
    }
    for numero, descricao in opcoes.items():
        print(f"  {numero} - {descricao}")
    print("  0 - Sair")
    imprimir_linha()


def main() -> None:
    """Controla o ciclo do programa: mostra o menu, chama a opção e trata erros."""
    oficina = Oficina()
    # Cada número do menu aponta para uma função de tela. Isso evita uma
    # sequência grande de if/elif e facilita incluir novas opções depois.
    acoes: dict[str, Callable[[Oficina], None]] = {
        "1": tela_cadastrar_concerto,
        "2": tela_listar_concertos,
        "3": tela_buscar_concerto,
        "4": tela_adicionar_peca,
        "5": mostrar_estoque,
        "6": tela_concluir_concerto,
        "7": tela_resumo,
    }

    while True:
        try:
            mostrar_menu()
            opcao = input("Escolha uma opção: ").strip()
            if opcao == "0":
                print("\nAté logo!")
                break
            acao = acoes.get(opcao)
            if acao is None:
                print("Opção inválida.")
            else:
                acao(oficina)
        except ErroOficina as erro:
            print(f"\nNão foi possível realizar a operação: {erro}")
        except (KeyboardInterrupt, EOFError):
            print("\n\nPrograma encerrado pelo usuário.")
            break
        pausar()
        limpar_terminal()


if __name__ == "__main__":
    main()
