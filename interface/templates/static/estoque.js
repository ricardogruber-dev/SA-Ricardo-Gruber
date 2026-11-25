document.addEventListener("DOMContentLoaded", function () {
  function iniciarEdicaoPeca(id) {
    // Fecha qualquer outra linha que já esteja aberta em edição
    document.querySelectorAll("tr.linha-editando").forEach(function (row) {
      if (row.dataset.pecaId !== id && row.style.display !== "none") {
        cancelarEdicaoPeca(row.dataset.pecaId);
      }
    });

    const viewRow = document.getElementById("peca-view-" + id);
    const editRow = document.getElementById("peca-edit-" + id);
    if (!viewRow || !editRow) return;

    viewRow.style.display = "none";
    editRow.style.display = "";

    const primeiroInput = editRow.querySelector('input[name="nome"]');
    if (primeiroInput) {
      primeiroInput.focus();
      primeiroInput.select();
    }
  }

  function cancelarEdicaoPeca(id) {
    const viewRow = document.getElementById("peca-view-" + id);
    const editRow = document.getElementById("peca-edit-" + id);
    if (!viewRow || !editRow) return;

    editRow.querySelectorAll("input[data-original]").forEach(function (input) {
      input.value = input.getAttribute("data-original");
      input.classList.remove("campo-erro");
    });

    editRow.querySelectorAll(".aviso-campo").forEach(function (aviso) {
      aviso.remove();
    });

    editRow.style.display = "none";
    viewRow.style.display = "";
  }

  // Botões Editar e Cancelar
  document.addEventListener("click", function (event) {
    const btnEditar = event.target.closest('[data-acao="editar"]');
    if (btnEditar) {
      iniciarEdicaoPeca(btnEditar.dataset.id);
      return;
    }

    const btnCancelar = event.target.closest('[data-acao="cancelar"]');
    if (btnCancelar) {
      cancelarEdicaoPeca(btnCancelar.dataset.id);
    }
  });

  // Atalho Esc para cancelar a edição da linha atual
  document.addEventListener("keydown", function (event) {
    if (event.key === "Escape") {
      const editRow = event.target.closest("tr.linha-editando");
      if (editRow) {
        cancelarEdicaoPeca(editRow.dataset.pecaId);
      }
    }
  });

  // Confirmação ao excluir peça
  document.addEventListener("submit", function (event) {
    const form = event.target.closest("form[data-confirm-exclusao]");
    if (!form) return;

    const nomePeca = form.getAttribute("data-confirm-exclusao");
    const confirmado = window.confirm(
      `Tem certeza que deseja excluir a peça '${nomePeca}' do estoque?`
    );
    if (!confirmado) {
      event.preventDefault();
    }
  });
});