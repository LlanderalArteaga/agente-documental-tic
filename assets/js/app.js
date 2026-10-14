
import { ApiClient } from './api.js';

const api = new ApiClient();
const el = id => document.getElementById(id);

const msg = (text, danger = false) => {
    el('message').textContent = text;
    el('message').className =
        'small mt-3 ' + (danger ? 'text-danger' : 'text-secondary');
};

function linkFor(source) {
    if (!source.url) return null;

    try {
        const u = new URL(source.url);

        if (
            u.protocol === 'https:' &&
            ['drive.google.com', 'docs.google.com'].includes(u.hostname)
        ) {
            return u.href;
        }
    } catch (_) {}

    return null;
}

async function loadDocuments() {
    const r = await api.documents();

    el('doc-count').textContent = r.indexed;

    const box = el('documents');
    box.replaceChildren();

    if (!r.documents.length) {
        box.textContent = 'Aún no hay documentos indexados.';
        return;
    }

    for (const d of r.documents) {
        const div = document.createElement('div');
        div.className = 'doc-item';

        const a = document.createElement('a');
        a.textContent = d.name;

        const href = linkFor(d);

        if (href) {
            a.href = href;
            a.target = '_blank';
            a.rel = 'noopener noreferrer';
        } else {
            a.removeAttribute('href');
        }

        div.append(a);
        box.append(div);
    }
}

async function ask() {
    const q = el('question').value.trim();

    if (q.length < 3) {
        msg('Escribe una pregunta de al menos 3 caracteres.', true);
        return;
    }

    el('ask').disabled = true;
    msg('Consultando al agente…');

    try {
        const data = await api.ask(q, el('use-search').checked);

        el('answer').textContent = data.answer || 'Sin respuesta.';

        const src = el('sources');
        src.replaceChildren();

        for (const source of data.sources) {
            const li = document.createElement('li');
            li.className = 'list-group-item px-0';

            const href = linkFor(source);

            if (href) {
                const a = document.createElement('a');
                a.href = href;
                a.target = '_blank';
                a.rel = 'noopener noreferrer';
                a.textContent = source.name;
                li.append(a);
            } else {
                li.textContent = source.name;
            }

            src.append(li);
        }

        if (!data.sources.length) {
            const li = document.createElement('li');
            li.className = 'list-group-item px-0 text-secondary';
            li.textContent =
                'No se recibieron citas verificables para esta respuesta.';
            src.append(li);
        }

        msg('Consulta finalizada.');
    } catch (e) {
        msg(e.message, true);
    } finally {
        el('ask').disabled = false;
    }
}

async function sync() {
    if (!confirm('¿Sincronizar archivos de la carpeta autorizada de Google Drive?')) {
        return;
    }

    el('sync').disabled = true;
    msg('Sincronizando documentos…');

    try {
        const r = await api.sync();
        await loadDocuments();

        msg(
            `Sincronización: ${r.stats.added} nuevos, ` +
            `${r.stats.updated} actualizados, ` +
            `${r.stats.removed} eliminados, ` +
            `${r.stats.unchanged} sin cambios. ` +
            `Errores: ${r.stats.errors.length}.`
        );
    } catch (e) {
        msg(e.message, true);
    } finally {
        el('sync').disabled = false;
    }
}

// Ocultar sincronización en el despliegue público de Vercel.
const isProductionDeployment =
    window.location.hostname === 'agente-documental-tic.vercel.app';

if (isProductionDeployment) {
    el('sync').classList.add('d-none');
}

el('ask').addEventListener('click', ask);
el('sync').addEventListener('click', sync);

el('question').addEventListener('keydown', e => {
    if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
        ask();
    }
});

api.health()
    .then(r => {
        el('health').textContent = r.configured
            ? 'Servidor listo'
            : 'Configuración pendiente';
    })
    .catch(() => {
        el('health').textContent = 'Sin conexión';
    });

loadDocuments().catch(e => msg(e.message, true));

// Inicio de sesión mediante cookie HttpOnly gestionada por el servidor.
const loginForm = el('login-form');

loginForm.addEventListener('submit', async event => {
    event.preventDefault();

    const input = el('admin-key');
    const button = el('login-button');
    const message = el('login-message');
    const key = input.value;

    button.disabled = true;
    message.textContent = 'Verificando acceso…';
    message.className = 'small mt-2 text-secondary';

    try {
        await api.login(key);

        input.value = '';
        el('login-panel').classList.add('d-none');
        message.textContent = '';

        msg('Sesión iniciada correctamente.');
    } catch (error) {
        message.textContent = error.message;
        message.className = 'small mt-2 text-danger';
    } finally {
        button.disabled = false;
    }
});
