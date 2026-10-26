import { ApiClient } from './api.js';

const api = new ApiClient();
const el = id => document.getElementById(id);

const msg = (text, danger = false) => {
    el('message').textContent = text;
    el('message').className = 'status-message' + (danger ? ' text-danger' : '');
};

function linkFor(source) {
    if (!source.url) return null;
    try {
        const url = new URL(source.url);
        if (url.protocol === 'https:' && ['drive.google.com', 'docs.google.com'].includes(url.hostname)) {
            return url.href;
        }
    } catch (_) {}
    return null;
}

async function loadDocuments() {
    const result = await api.documents();
    el('doc-count').textContent = result.indexed;
    if (result.active_folder_id && !el('folder-id').value) {
        el('folder-id').value = result.active_folder_id;
    }

    const box = el('documents');
    box.replaceChildren();
    const documentPrompt = el('suggested-questions').querySelector('.suggestion-button:last-child');
    if (!result.documents.length) {
        box.textContent = 'Aun no hay documentos indexados.';
        documentPrompt.textContent = '¿Qué información importante contienen?';
        documentPrompt.dataset.prompt = '¿Qué información importante contienen mis documentos?';
        return;
    }
    const sampleName = result.documents[0].name;
    documentPrompt.textContent = `Pregunta sobre: ${sampleName}`;
    documentPrompt.dataset.prompt = `¿Qué información importante contiene el documento "${sampleName}"?`;
    for (const item of result.documents) {
        const div = document.createElement('div');
        div.className = 'doc-item';
        const anchor = document.createElement('a');
        anchor.textContent = item.name;
        const href = linkFor(item);
        if (href) {
            anchor.href = href;
            anchor.target = '_blank';
            anchor.rel = 'noopener noreferrer';
        }
        div.append(anchor);
        box.append(div);
    }
}

async function ask() {
    const question = el('question').value.trim();
    if (question.length < 3) {
        msg('Escribe una pregunta de al menos 3 caracteres.', true);
        return;
    }
    el('ask').disabled = true;
    msg('Consultando al agente...');
    try {
        const data = await api.ask(question, el('use-search').checked);
        el('answer').textContent = data.answer || 'Sin respuesta.';
        const sources = el('sources');
        sources.replaceChildren();
        for (const source of data.sources) {
            const li = document.createElement('li');
            li.className = 'list-group-item px-0';
            const href = linkFor(source);
            if (href) {
                const anchor = document.createElement('a');
                anchor.href = href;
                anchor.target = '_blank';
                anchor.rel = 'noopener noreferrer';
                anchor.textContent = source.name;
                li.append(anchor);
            } else {
                li.textContent = source.name;
            }
            sources.append(li);
        }
        if (!data.sources.length) {
            const li = document.createElement('li');
            li.className = 'list-group-item px-0 text-secondary';
            li.textContent = 'No se recibieron citas verificables para esta respuesta.';
            sources.append(li);
        }
        msg('Consulta finalizada.');
    } catch (error) {
        msg(error.message, true);
    } finally {
        el('ask').disabled = false;
    }
}

async function sync() {
    const folderId = el('folder-id').value.trim();
    if (!folderId) {
        msg('Pega el ID o enlace de la carpeta que quieres sincronizar.', true);
        el('folder-id').focus();
        return;
    }
    if (!confirm('La sincronizacion reemplaza el indice de la carpeta anterior si eliges otra. Continuar?')) return;

    el('sync').disabled = true;
    msg('Sincronizando carpeta...');
    try {
        const result = await api.sync(folderId);
        await loadDocuments();
        msg(
            `Sincronizacion: ${result.stats.added} nuevos, ${result.stats.updated} actualizados, ` +
            `${result.stats.removed} eliminados, ${result.stats.unchanged} sin cambios. ` +
            `Errores: ${result.stats.errors.length}.`
        );
    } catch (error) {
        msg(error.message, true);
    } finally {
        el('sync').disabled = false;
    }
}

el('ask').addEventListener('click', ask);
el('sync').addEventListener('click', sync);
el('suggested-questions').addEventListener('click', event => {
    const button = event.target.closest('[data-prompt]');
    if (!button) return;
    el('question').value = button.dataset.prompt;
    el('question').focus();
});
el('question').addEventListener('keydown', event => {
    if (event.key === 'Enter' && (event.ctrlKey || event.metaKey)) ask();
});

api.health().then(result => {
    el('health').textContent = result.configured ? 'Agente disponible' : 'Falta configurar OpenAI';
}).catch(() => {
    el('health').textContent = 'Sin conexión';
});

loadDocuments().catch(error => {
    el('documents').textContent = error.message;
});
