
# Devolutiva formativa — Atividade 01 da SA

**Estudante:** Ricardo  
**Turma:** Rio Negrinho — Tarde  
**Unidade Curricular:** Programação de Aplicativos  
**Projeto:** Sistema de Oficina Mecânica  
**Código analisado:** `codigo/app.py`  
**Referência:** Situação de Aprendizagem nº 1 — *Da Ideia ao Código*

## O que você já conseguiu desenvolver

Ricardo, seu projeto apresenta uma estrutura técnica bem organizada para gerenciar atendimentos, peças, estoque e serviços de uma oficina mecânica. Você utilizou recursos do Python que favorecem a clareza das regras e a manutenção do programa.

Pontos positivos identificados:

- Utilizou **classes e `dataclass`** para representar entidades do sistema.
- Criou **exceções específicas**, como `DadoInvalido`, `RegistroNaoEncontrado` e `OperacaoNaoPermitida`.
- Implementou validações reutilizáveis para textos, quantidades e valores monetários.
- Utilizou **`Decimal`** para representar dinheiro, evitando depender exclusivamente de números de ponto flutuante.
- Criou um `Enum` para representar as situações dos atendimentos.
- Desenvolveu operações de cadastro, busca, utilização de peças e acompanhamento de serviços.
- Implementou controle de estoque, incluindo verificação de disponibilidade.
- Separou regras de negócio e funções de apresentação em terminal.
- Incluiu docstrings e comentários que facilitam a leitura do código.

## O que precisa ser corrigido

### 1. Corrigir a nomenclatura dos atendimentos

O projeto utiliza repetidamente o termo `concerto`, como nas classes e funções relacionadas à manutenção dos veículos. No contexto de oficina mecânica, a grafia adequada é **conserto**.

**Como melhorar:** padronizar nomes de classes, métodos, atributos e mensagens com a terminologia correta. Ao renomear, utilizar os recursos da IDE para atualizar todas as referências sem interromper o funcionamento do programa.

### 2. Disponibilizar a consulta ao histórico de estoque

A função `tela_historico_estoque()` foi implementada, mas não aparece entre as ações vinculadas ao menu principal.

**Como melhorar:** adicionar uma opção específica para acessar o histórico, incluindo a função no dicionário `acoes` utilizado em `main()`.

## Oportunidades de melhoria

### 3. Organizar o projeto em módulos

Embora o código esteja bem dividido em classes e funções, todas as responsabilidades permanecem em um único arquivo extenso.

**Como melhorar:** separar gradualmente os modelos, as validações, as regras da oficina e a interação com o usuário. Isso permitirá localizar funcionalidades com mais facilidade e desenvolver testes específicos.

### 4. Preparar o armazenamento permanente

O programa informa corretamente que os dados são mantidos em memória e perdidos ao encerrar a execução.

Essa característica não representa uma falha da Atividade 01, mas deve ser considerada na evolução da aplicação.

**Próximo passo:** definir uma estratégia de persistência para os atendimentos, peças e movimentações na etapa correspondente da Situação de Aprendizagem.

### 5. Ampliar a verificação das regras de negócio

O sistema possui várias validações, mas é importante comprovar o funcionamento de situações que envolvem alterações relacionadas.

**Como melhorar:** testar especialmente o uso de peças, o encerramento de serviços, os cálculos monetários e as tentativas de executar operações não permitidas.

### 6. Complementar a documentação de execução

O código apresenta boa documentação interna, mas o README ainda pode explicar melhor as funcionalidades específicas da aplicação.

**Como melhorar:** incluir instruções para executar o programa, informações sobre a versão necessária do Python, exemplos de uso e as limitações da versão atual.

## Testes recomendados

1. Cadastrar um atendimento com dados válidos.
2. Informar campos obrigatórios vazios.
3. Cadastrar e repor peças no estoque.
4. Tentar utilizar uma quantidade maior que o estoque disponível.
5. Iniciar, acompanhar e concluir um atendimento.
6. Tentar alterar um atendimento já concluído.
7. Conferir os valores de peças, mão de obra e faturamento.
8. Consultar o histórico de movimentações após disponibilizá-lo no menu.

## Prioridades para a próxima versão

1. **Padronizar a nomenclatura de conserto.**
2. **Adicionar o histórico de estoque ao menu.**
3. **Separar o sistema em módulos para facilitar a manutenção.**
4. **Registrar testes das regras de negócio.**
5. **Complementar o README com instruções de execução.**

## Mensagem final

Ricardo, seu projeto demonstra domínio de conceitos importantes de programação, principalmente **orientação a objetos, tipagem, tratamento de exceções, validação e organização de regras de negócio**.

A utilização de `Decimal`, exceções específicas e estruturas próprias para representar os dados mostra preocupação com a qualidade da solução.

Continue aprimorando a documentação, a modularização e os testes. **A base do sistema está bem estruturada, e esses ajustes ajudarão a torná-lo ainda mais consistente e fácil de manter.**
