(() => {
    const widget = document.getElementById('notificationWidget');
    if (!widget) return;

    const launcher = document.getElementById('notificationLauncher');
    const panel = document.getElementById('notificationPanel');
    const closeButton = document.getElementById('notificationClose');
    const clearButton = document.getElementById('notificationClear');
    const count = document.getElementById('notificationCount');
    const summary = document.getElementById('notificationSummary');
    const list = document.getElementById('notificationList');
    const empty = document.getElementById('notificationEmpty');
    const emptyTitle = document.getElementById('notificationEmptyTitle');
    const emptyText = document.getElementById('notificationEmptyText');
    let notifications = [];
    let snapshotFresh = true;
    const baseDocumentTitle = document.title.replace(/^\(\d+\+?\)\s*/, '');

    const setDocumentTitleCount = (value) => {
        const amount = Number(value || 0);
        document.title = amount > 0
            ? `(${amount}) ${baseDocumentTitle}`
            : baseDocumentTitle;
    };

    const setCount = (value) => {
        const amount = Number(value || 0);
        count.textContent = amount > 99 ? '99+' : String(amount);
        count.hidden = amount === 0;
        launcher.setAttribute('aria-label', amount ? `Abrir notificações, ${amount} pendentes` : 'Abrir notificações');
        setDocumentTitleCount(amount);
    };

    const formatDate = (value) => {
        if (!value) return 'Horário não informado';
        const date = new Date(value);
        return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleString('pt-BR');
    };

    const render = () => {
        list.replaceChildren();
        empty.hidden = notifications.length > 0;
        list.hidden = notifications.length === 0;
        if (!snapshotFresh) {
            summary.textContent = 'Atualizando o estado operacional...';
            emptyTitle.textContent = 'Dados operacionais desatualizados';
            emptyText.textContent = 'Uma atualização foi iniciada. Os alertas aparecerão após a nova coleta.';
        } else {
            summary.textContent = notifications.length === 1 ? '1 alerta ativo' : `${notifications.length} alertas ativos`;
            emptyTitle.textContent = 'Tudo tranquilo por aqui';
            emptyText.textContent = 'Nenhum alerta crítico ou importante no snapshot atual.';
        }

        notifications.forEach((notification) => {
            const item = document.createElement('a');
            item.className = `notification-item ${notification.severity || 'important'}${notification.read ? '' : ' is-unread'}`;
            item.href = notification.url || '#';

            const icon = document.createElement('span');
            icon.className = 'notification-item-icon';
            const iconGlyph = document.createElement('i');
            iconGlyph.className = `bi ${notification.icon || 'bi-exclamation-triangle'}`;
            icon.appendChild(iconGlyph);

            const copy = document.createElement('span');
            copy.className = 'notification-item-copy';
            const title = document.createElement('strong');
            title.textContent = notification.title;
            const message = document.createElement('p');
            message.textContent = notification.message;
            const meta = document.createElement('small');
            meta.textContent = `${notification.regional || 'Sem regional'} · ${formatDate(notification.occurred_at)}`;
            copy.append(title, message, meta);

            const dot = document.createElement('span');
            dot.className = 'notification-unread-dot';
            dot.hidden = Boolean(notification.read);
            item.append(icon, copy, dot);
            list.appendChild(item);
        });
    };

    const load = async () => {
        try {
            const response = await fetch(widget.dataset.listUrl, { headers: { Accept: 'application/json' } });
            if (!response.ok) throw new Error(`HTTP ${response.status}`);
            const payload = await response.json();
            notifications = payload.notifications || [];
            snapshotFresh = payload.snapshot_fresh !== false;
            setCount(payload.unread_count);
            render();
        } catch (error) {
            summary.textContent = 'Não foi possível carregar os alertas';
        }
    };

    const markVisibleAsRead = async () => {
        const ids = notifications.filter((item) => !item.read).map((item) => item.id);
        if (!ids.length) return;
        notifications = notifications.map((item) => ({ ...item, read: true }));
        setCount(0);
        render();
        try {
            await fetch(widget.dataset.seenUrl, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
                body: JSON.stringify({ ids }),
            });
        } catch (error) {
            await load();
        }
    };

    const clearNotifications = async () => {
        const ids = notifications.map((item) => item.id);
        if (!ids.length) return;
        clearButton.disabled = true;
        try {
            const response = await fetch(widget.dataset.clearUrl, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
                body: JSON.stringify({ ids }),
            });
            if (!response.ok) throw new Error(`HTTP ${response.status}`);
            await load();
        } catch (error) {
            summary.textContent = 'Não foi possível limpar as notificações';
        } finally {
            clearButton.disabled = false;
        }
    };

    const open = async () => {
        panel.hidden = false;
        launcher.setAttribute('aria-expanded', 'true');
        await markVisibleAsRead();
    };

    const close = () => {
        panel.hidden = true;
        launcher.setAttribute('aria-expanded', 'false');
    };

    launcher.addEventListener('click', () => panel.hidden ? open() : close());
    closeButton.addEventListener('click', close);
    clearButton.addEventListener('click', clearNotifications);
    document.addEventListener('keydown', (event) => {
        if (event.key === 'Escape' && !panel.hidden) close();
    });

    load();
    window.setInterval(load, 30000);
})();
