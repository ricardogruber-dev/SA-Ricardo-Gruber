-- =====================================================================
-- SISTEMA DE OFICINA MECÂNICA – ESTRUTURA DO BANCO (PostgreSQL 11+)
--
-- Substitui os arquivos JSON do app.py:
--   estoque.json       -> peca
--   consertos.json     -> conserto + item_conserto + comentario_conserto
--   movimentacoes.json -> movimentacao_estoque
--
-- Ordem do script: tabelas -> índices -> triggers -> views.
-- As tabelas "filhas" (item_conserto, comentario_conserto,
-- movimentacao_estoque) vêm depois das "pais" (peca, conserto), porque
-- uma chave estrangeira só pode apontar para uma tabela que já existe.
--
-- Este script cria o banco do zero.
-- =====================================================================
-- ---------------------------------------------------------------------
-- 1. PEÇAS (estoque)
-- ---------------------------------------------------------------------
CREATE TABLE peca (
    -- GENERATED ALWAYS AS IDENTITY: o banco gera o id sozinho (1, 2, 3...)
    -- e não aceita que o app informe um id manualmente.
    id           INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    nome         VARCHAR(120)  NOT NULL,
    quantidade   INTEGER       NOT NULL DEFAULT 0,   -- começa em 0 se não informado
    -- NUMERIC(12,2) = até 12 dígitos, 2 casas decimais. Usado para dinheiro
    -- (equivale ao Decimal do Python; float causaria erros de arredondamento).
    preco_custo  NUMERIC(12,2) NOT NULL,             -- quanto a oficina paga
    preco_venda  NUMERIC(12,2) NOT NULL,             -- quanto o cliente paga
    -- Toda peça acaba com histórico em movimentacao_estoque (fk_mov_peca é
    -- RESTRICT), então ela nunca pode ser apagada com DELETE. "Excluir" uma
    -- peça significa marcar ativo = false; o app deixa de mostrá-la nas listas
    -- (WHERE ativo), mas o histórico e os consertos antigos continuam intactos.
    ativo        BOOLEAN       NOT NULL DEFAULT true,
    -- btrim() remove espaços das pontas: impede nome vazio ou só com espaços.
    CONSTRAINT ck_peca_nome_preenchido CHECK (btrim(nome) <> ''),
    CONSTRAINT ck_peca_quantidade      CHECK (quantidade >= 0),   -- estoque nunca fica negativo
    CONSTRAINT ck_peca_preco_custo     CHECK (preco_custo >= 0),
    CONSTRAINT ck_peca_preco_venda     CHECK (preco_venda >= 0)
);

-- O app trata "Filtro de Óleo" e "filtro de óleo" como a mesma peça (casefold).
-- Um índice único sobre lower(nome) faz o banco recusar nomes repetidos
-- mesmo que mudem as letras maiúsculas/minúsculas.
-- Vale também para peças inativas: para voltar a usar o nome, reative a peça.
CREATE UNIQUE INDEX uq_peca_nome ON peca (lower(nome));

-- ---------------------------------------------------------------------
-- 2. CONSERTOS (atendimentos)
-- ---------------------------------------------------------------------
CREATE TABLE conserto (
    id             INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    cliente        VARCHAR(120)      NOT NULL,
    veiculo        VARCHAR(120)      NOT NULL,   -- "modelo/placa"
    mecanico       VARCHAR(120)      NOT NULL,
    problema       TEXT              NOT NULL,   -- TEXT: sem limite de tamanho
    -- VARCHAR + CHECK no lugar de ENUM: é mais fácil de alterar depois
    -- (ex.: incluir 'Cancelado') sem precisar mexer em um tipo do banco.
    situacao       VARCHAR(20)   NOT NULL DEFAULT 'Pendente',
    mao_de_obra    NUMERIC(12,2)     NOT NULL DEFAULT 0,
    valor_total    NUMERIC(12,2),   -- peças + mão de obra, gravado só ao concluir
    -- TIMESTAMP(0): data e hora sem frações de segundo.
    -- DEFAULT now(): se o app não informar, usa o momento do cadastro.
    data_entrada   TIMESTAMP(0)      NOT NULL DEFAULT now(),
    data_conclusao TIMESTAMP(0),                 -- fica NULL até concluir
    CONSTRAINT ck_conserto_cliente   CHECK (btrim(cliente)  <> ''),
    CONSTRAINT ck_conserto_veiculo   CHECK (btrim(veiculo)  <> ''),
    CONSTRAINT ck_conserto_mecanico  CHECK (btrim(mecanico) <> ''),
    CONSTRAINT ck_conserto_problema  CHECK (btrim(problema) <> ''),
    -- Só estes três valores são aceitos (os mesmos do app).
    CONSTRAINT ck_conserto_situacao  CHECK (situacao IN ('Pendente', 'Em execução', 'Concluído')),
    CONSTRAINT ck_conserto_mao_obra  CHECK (mao_de_obra >= 0),
    -- valor_total existe se, e somente se, o conserto está concluído
    -- Lógica: ou (concluído E com valor, que não pode ser menor que a mão
    -- de obra) OU (não concluído E sem valor). Qualquer outra combinação
    -- é rejeitada pelo banco.
    CONSTRAINT ck_conserto_valor_total CHECK (
        (situacao = 'Concluído' AND valor_total IS NOT NULL AND valor_total >= mao_de_obra)
        OR
        (situacao <> 'Concluído' AND valor_total IS NULL)
    ),
    -- data_conclusao existe se, e somente se, o conserto está concluído
    -- Mesma ideia, e ainda garante que a conclusão não é anterior à entrada.
    CONSTRAINT ck_conserto_conclusao CHECK (
        (situacao = 'Concluído' AND data_conclusao IS NOT NULL AND data_conclusao >= data_entrada)
        OR
        (situacao <> 'Concluído' AND data_conclusao IS NULL)
    )
);

-- Acelera filtros por situação (ex.: listar só os Pendentes).
CREATE INDEX ix_conserto_situacao     ON conserto (situacao);
-- DESC: listagens "mais recentes primeiro" ficam rápidas.
CREATE INDEX ix_conserto_data_entrada ON conserto (data_entrada DESC);

-- ---------------------------------------------------------------------
-- 3. PEÇAS USADAS EM CADA CONSERTO
--    preco_unitario guarda o preço de venda NO MOMENTO do uso, para que
--    mudanças futuras no estoque não alterem consertos antigos.
--
--    É a tabela que liga conserto e peça (relação N:N): um conserto usa
--    várias peças, e uma peça aparece em vários consertos.
-- ---------------------------------------------------------------------
CREATE TABLE item_conserto (
    id             INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    conserto_id    INTEGER       NOT NULL,
    peca_id        INTEGER       NOT NULL,
    quantidade     INTEGER       NOT NULL,
    preco_unitario NUMERIC(12,2) NOT NULL,
    -- ON DELETE CASCADE: apagando o conserto, seus itens somem junto.
    CONSTRAINT fk_item_conserto
        FOREIGN KEY (conserto_id) REFERENCES conserto (id) ON DELETE CASCADE,
    -- ON DELETE RESTRICT: não deixa apagar uma peça que já foi usada
    -- em algum conserto (protege o histórico).
    CONSTRAINT fk_item_peca
        FOREIGN KEY (peca_id) REFERENCES peca (id) ON DELETE RESTRICT,
    CONSTRAINT ck_item_quantidade CHECK (quantidade > 0),   -- usar 0 peça não faz sentido
    CONSTRAINT ck_item_preco      CHECK (preco_unitario >= 0)
);

-- O PostgreSQL NÃO cria índice automático em chave estrangeira.
-- Estes dois aceleram "itens deste conserto" e "consertos desta peça".
CREATE INDEX ix_item_conserto ON item_conserto (conserto_id);
CREATE INDEX ix_item_peca     ON item_conserto (peca_id);

-- ---------------------------------------------------------------------
-- 4. COMENTÁRIOS DO MECÂNICO
-- ---------------------------------------------------------------------
CREATE TABLE comentario_conserto (
    id          INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    conserto_id INTEGER      NOT NULL,
    mecanico    VARCHAR(120) NOT NULL,   -- quem escreveu (pode ser diferente do responsável)
    texto       TEXT         NOT NULL,
    data_hora   TIMESTAMP(0) NOT NULL DEFAULT now(),
    -- Apagou o conserto, apagam-se os comentários dele.
    CONSTRAINT fk_comentario_conserto
        FOREIGN KEY (conserto_id) REFERENCES conserto (id) ON DELETE CASCADE,
    CONSTRAINT ck_comentario_mecanico CHECK (btrim(mecanico) <> ''),
    CONSTRAINT ck_comentario_texto    CHECK (btrim(texto)    <> '')
);

-- Índice composto: busca os comentários de um conserto já ordenados por data.
CREATE INDEX ix_comentario_conserto ON comentario_conserto (conserto_id, data_hora);

-- ---------------------------------------------------------------------
-- 5. HISTÓRICO DE MOVIMENTAÇÕES DO ESTOQUE
--    conserto_id só é preenchido nas saídas feitas para um conserto.
-- ---------------------------------------------------------------------
CREATE TABLE movimentacao_estoque (
    id          INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    peca_id     INTEGER           NOT NULL,
    conserto_id INTEGER,                      -- pode ser NULL (ex.: compra de peças)
    tipo        VARCHAR(10)       NOT NULL,   -- 'Entrada' ou 'Saída'
    quantidade  INTEGER           NOT NULL,
    motivo      VARCHAR(200)      NOT NULL,   -- explica a movimentação
    data_hora   TIMESTAMP(0)      NOT NULL DEFAULT now(),
    -- Peça com histórico não pode ser apagada.
    CONSTRAINT fk_mov_peca
        FOREIGN KEY (peca_id) REFERENCES peca (id) ON DELETE RESTRICT,
    -- Se o conserto for apagado, o histórico do estoque permanece,
    -- apenas perde o vínculo (conserto_id vira NULL).
    CONSTRAINT fk_mov_conserto
        FOREIGN KEY (conserto_id) REFERENCES conserto (id) ON DELETE SET NULL,
    CONSTRAINT ck_mov_tipo       CHECK (tipo IN ('Entrada', 'Saída')),
    CONSTRAINT ck_mov_quantidade CHECK (quantidade > 0),   -- o sentido (entra/sai) está em "tipo"
    CONSTRAINT ck_mov_motivo     CHECK (btrim(motivo) <> '')
);

CREATE INDEX ix_mov_peca      ON movimentacao_estoque (peca_id);
CREATE INDEX ix_mov_conserto  ON movimentacao_estoque (conserto_id);
CREATE INDEX ix_mov_data_hora ON movimentacao_estoque (data_hora DESC);

-- ---------------------------------------------------------------------
-- 6. REGRA DE NEGÓCIO NO BANCO
--    Conserto concluído não aceita novas peças nem comentários
--    (a mesma regra que o app.py já valida em Python).
--
--    Por que no banco também? Porque o banco é a última barreira:
--    mesmo que outro programa (ou um INSERT manual no pgAdmin) tente
--    burlar a validação do app, a regra continua valendo.
-- ---------------------------------------------------------------------
-- Função de trigger: não recebe parâmetros e devolve "trigger".
-- Serve para as duas tabelas (item_conserto e comentario_conserto),
-- pois ambas têm a coluna conserto_id.
CREATE OR REPLACE FUNCTION fn_bloquear_conserto_concluido()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    v_situacao VARCHAR(20);   -- guarda a situação atual do conserto
BEGIN
    -- FOR SHARE impede que o conserto seja concluído por outra
    -- transação enquanto este registro está sendo inserido.
    -- (NEW = a linha que está sendo inserida.)
    SELECT situacao INTO v_situacao
      FROM conserto
     WHERE id = NEW.conserto_id
       FOR SHARE;

    IF v_situacao = 'Concluído' THEN
        -- RAISE EXCEPTION cancela o INSERT e devolve esta mensagem ao app.
        -- O % é substituído pelo id do conserto.
        RAISE EXCEPTION 'O conserto % já está concluído e não aceita alterações.', NEW.conserto_id;
    END IF;
    -- Devolver NEW autoriza a inserção seguir normalmente.
    RETURN NEW;
END;
$$;

-- BEFORE INSERT: roda antes de gravar a linha, podendo barrá-la.
-- FOR EACH ROW: executa uma vez para cada linha inserida.
-- Obs.: protege apenas INSERT; UPDATE e DELETE nessas tabelas não são bloqueados.
CREATE TRIGGER trg_item_conserto_bloqueio
    BEFORE INSERT ON item_conserto
    FOR EACH ROW EXECUTE FUNCTION fn_bloquear_conserto_concluido();

CREATE TRIGGER trg_comentario_bloqueio
    BEFORE INSERT ON comentario_conserto
    FOR EACH ROW EXECUTE FUNCTION fn_bloquear_conserto_concluido();

-- Ao concluir um conserto, grava o valor final (peças + mão de obra) uma única vez.
-- Roda ANTES do UPDATE ser gravado, então o CHECK ck_conserto_valor_total já o encontra preenchido.
CREATE OR REPLACE FUNCTION fn_fechar_valor_conserto()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    -- Em UPDATE, NEW é a linha como ficará depois da alteração.
    -- Atribuir a NEW.valor_total altera o valor que será gravado.
    -- COALESCE(..., 0): se o conserto não tiver peças, o SUM é NULL
    -- e o resultado vira 0, ficando só a mão de obra.
    NEW.valor_total := NEW.mao_de_obra + COALESCE(
        (SELECT SUM(quantidade * preco_unitario)
           FROM item_conserto
          WHERE conserto_id = NEW.id), 0);
    RETURN NEW;
END;
$$;

-- BEFORE UPDATE OF situacao: só dispara quando a coluna situacao é alterada.
-- WHEN: e só na transição para 'Concluído' (OLD = valores antes da alteração).
-- Assim, o valor é calculado uma vez e não é refeito em updates posteriores.
CREATE TRIGGER trg_conserto_fechar_valor
    BEFORE UPDATE OF situacao ON conserto
    FOR EACH ROW
    WHEN (NEW.situacao = 'Concluído' AND OLD.situacao <> 'Concluído')
    EXECUTE FUNCTION fn_fechar_valor_conserto();

-- Ao EXCLUIR um conserto que não foi concluído, devolve ao estoque as peças
-- que ele tinha usado. Sem isto, o ON DELETE CASCADE apagaria os itens e o
-- estoque continuaria descontado.
-- Conserto CONCLUÍDO: as peças já foram instaladas no veículo, então NÃO voltam.
-- A trigger é BEFORE DELETE porque o CASCADE só apaga os itens depois (é um
-- gatilho AFTER): neste momento item_conserto ainda tem as linhas do conserto.
CREATE OR REPLACE FUNCTION fn_devolver_estoque_conserto()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    r RECORD;
BEGIN
    -- OLD = a linha de conserto que está sendo excluída.
    IF OLD.situacao <> 'Concluído' THEN
        -- Agrupa por peça: o mesmo conserto pode ter a mesma peça em
        -- mais de uma linha de item_conserto.
        FOR r IN
            SELECT peca_id, SUM(quantidade)::INTEGER AS qtd
              FROM item_conserto
             WHERE conserto_id = OLD.id
             GROUP BY peca_id
        LOOP
            UPDATE peca
               SET quantidade = quantidade + r.qtd
             WHERE id = r.peca_id;

            -- conserto_id fica NULL: esse conserto está sendo apagado.
            -- O número dele vai no motivo para o histórico continuar legível.
            INSERT INTO movimentacao_estoque (peca_id, tipo, quantidade, motivo)
            VALUES (r.peca_id, 'Entrada', r.qtd,
                    'Estorno: conserto #' || OLD.id || ' excluído');
        END LOOP;
    END IF;
    RETURN OLD;   -- em BEFORE DELETE, devolver OLD deixa a exclusão seguir
END;
$$;

CREATE TRIGGER trg_conserto_devolver_estoque
    BEFORE DELETE ON conserto
    FOR EACH ROW EXECUTE FUNCTION fn_devolver_estoque_conserto();

-- ---------------------------------------------------------------------
-- 7. VIEWS (cálculos que o app fazia em Python)
--    View = consulta salva com nome; usa-se como se fosse uma tabela
--    (SELECT * FROM vw_...), sem guardar dados duplicados.
-- ---------------------------------------------------------------------

-- Total de peças e total geral de cada conserto, calculado na hora.
-- Serve para consertos em aberto; nos concluídos vale conserto.valor_total.
CREATE VIEW vw_conserto_totais AS
SELECT c.id AS conserto_id,
       c.situacao,
       c.mao_de_obra,
       -- LEFT JOIN traz também consertos sem peças; nesses o SUM é NULL,
       -- por isso o COALESCE(…, 0). O ::NUMERIC(12,2) fixa as 2 casas decimais.
       COALESCE(SUM(i.quantidade * i.preco_unitario), 0)::NUMERIC(12,2) AS total_pecas,
       (COALESCE(SUM(i.quantidade * i.preco_unitario), 0) + c.mao_de_obra)::NUMERIC(12,2) AS total
  FROM conserto c
  LEFT JOIN item_conserto i ON i.conserto_id = c.id
 GROUP BY c.id;   -- basta agrupar pelo id (chave primária) para usar as outras colunas de c

-- Histórico exibido na tela "Histórico do estoque" (mais recente primeiro)
CREATE VIEW vw_historico_estoque AS
SELECT m.id,
       m.data_hora,
       m.tipo,
       p.nome AS nome_peca,   -- junta com peca para mostrar o nome em vez do id
       m.quantidade,
       m.motivo,
       m.conserto_id
  FROM movimentacao_estoque m
  JOIN peca p ON p.id = m.peca_id
 ORDER BY m.data_hora DESC, m.id DESC;   -- o id desempata movimentações do mesmo segundo

-- Indicadores da página inicial (uma única linha)
-- Cada subconsulta entre parênteses devolve um número só.
CREATE VIEW vw_resumo_oficina AS
SELECT (SELECT COUNT(*) FROM conserto)                               AS total_consertos,
       (SELECT COUNT(*) FROM conserto WHERE situacao = 'Pendente')    AS pendentes,
       (SELECT COUNT(*) FROM conserto WHERE situacao = 'Em execução') AS em_execucao,
       (SELECT COUNT(*) FROM conserto WHERE situacao = 'Concluído')   AS concluidos,
       -- Faturamento = soma do valor_total dos concluídos (SUM sem linhas dá NULL, daí o COALESCE).
       COALESCE((SELECT SUM(valor_total) FROM conserto
                  WHERE situacao = 'Concluído'), 0)                   AS faturamento,
       -- Valor do estoque calculado pelo preço de CUSTO (o que a oficina gastou), não pelo de venda.
       -- Inclui peças inativas: se ainda há unidades guardadas, elas continuam valendo dinheiro.
       COALESCE((SELECT SUM(quantidade * preco_custo) FROM peca), 0)  AS valor_estoque;