(function() {

    const style = document.createElement('style');
    style.innerHTML = `
        #gpb-widget-btn { position: fixed; bottom: 25px; right: 25px; width: 60px; height: 60px; background: linear-gradient(135deg, #0073ff, #0043b3); border-radius: 50%; color: white; font-size: 26px; border: none; cursor: pointer; box-shadow: 0 4px 15px rgba(0,82,204,0.4); z-index: 9999; display: flex; align-items: center; justify-content: center; transition: transform 0.2s; }
        #gpb-widget-btn:hover { transform: scale(1.05); }
        #gpb-chat-window { position: fixed; bottom: 95px; right: 25px; width: 430px; height: 550px; background: #f4f6fa; border-radius: 16px; box-shadow: 0 5px 25px rgba(0,0,0,0.15); display: none; flex-direction: column; font-family: -apple-system, BlinkMacSystemFont, Arial, sans-serif; z-index: 9999; overflow: hidden; border: 1px solid #d2d9e5; }
        #gpb-chat-header { background: #003399; color: white; padding: 15px 20px; font-weight: bold; font-size: 15px; letter-spacing: 0.5px; }
        #gpb-chat-messages { flex: 1; padding: 15px; overflow-y: auto; display: flex; flex-direction: column; gap: 10px; }
        .gpb-msg { padding: 10px 14px; border-radius: 12px; max-width: 85%; font-size: 13px; line-height: 1.4; }
        .gpb-user-msg { background: #0052cc; color: white; align-self: flex-end; border-bottom-right-radius: 2px; }
        .gpb-bot-msg { background: white; color: #141414; align-self: flex-start; border: 1px solid #e2e5ec; border-bottom-left-radius: 2px; width: 93%; }
        #gpb-chat-input-area { display: flex; padding: 12px; background: white; border-top: 1px solid #e2e5ec; gap: 8px; }
        #gpb-chat-input { flex: 1; border: 1px solid #d2d9e5; border-radius: 20px; padding: 8px 15px; outline: none; font-size: 13px; color: #141414 !important; background: white !important; }
        #gpb-chat-send { background: #0052cc; color: white; border: none; border-radius: 50%; width: 35px; height: 35px; cursor: pointer; font-weight: bold; display: flex; align-items: center; justify-content: center; }
        .gpb-warning { color: #cc3300; background: #fff0f0; border: 1px solid #ffcccc; padding: 8px; border-radius: 8px; margin-top: 5px; font-size: 12px; font-weight: bold; }
        .gpb-table-container { width: 100%; overflow-x: auto; margin-top: 10px; border-radius: 8px; border: 1px solid #d2d9e5; }
        .gpb-table { width: 100%; border-collapse: collapse; font-size: 11px; }
        .gpb-table th { background: #f4f8ff; color: #003399; padding: 8px; border: 1px solid #d2d9e5; font-weight: bold; }
        .gpb-table td { padding: 8px; border: 1px solid #f0f4fa; background: white; text-align: center; color: #141414; }
        .gpb-sql-block { background: #f8fafc; color: #0052cc; font-family: monospace; padding: 8px; border-radius: 8px; margin-top: 8px; font-size: 11px; border-left: 3px solid #0052cc; white-space: pre-wrap; word-break: break-all; }
    `;
    document.head.appendChild(style);

    const btn = document.createElement('button');
    btn.id = 'gpb-widget-btn';
    btn.innerHTML = '💬';
    document.body.appendChild(btn);

    const chatWindow = document.createElement('div');
    chatWindow.id = 'gpb-chat-window';
    chatWindow.innerHTML = `
        <div id="gpb-chat-header">Газпромбанк — Университетский Ассистент</div>
        <div id="gpb-chat-messages"></div>
        <div id="gpb-chat-input-area">
            <input type="text" id="gpb-chat-input" placeholder="Задайте вопрос по базе данных ВУЗа...">
            <button id="gpb-chat-send">➔</button>
        </div>
    `;
    document.body.appendChild(chatWindow);

    btn.onclick = () => {
        chatWindow.style.display = chatWindow.style.display === 'flex' ? 'none' : 'flex';
    };

    const sendBtn = document.getElementById('gpb-chat-send');
    const inputField = document.getElementById('gpb-chat-input');
    const msgContainer = document.getElementById('gpb-chat-messages');

    async function sendQuery() {
        const query = inputField.value.trim();
        if (!query) return;

        appendMessage(query, 'gpb-user-msg');
        inputField.value = '';

        const loadingMsg = appendMessage('Анализирую базу данных...', 'gpb-bot-msg');

        try {

            const response = await fetch('http://100.88.109.88:5000/api/query', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ question: query })
            });

            const data = await response.json();
            msgContainer.removeChild(loadingMsg);

            if (data.success) {
                let botHtml = `<div>Анализ завершен успешно. Сформирован ответ:</div>`;
                botHtml += `<div class="gpb-sql-block">${data.sql}</div>`;
                
                if (data.warning) {
                    botHtml += `<div class="gpb-warning">${data.warning}</div>`;
                }

                let tableHtml = `<div class="gpb-table-container"><table class="gpb-table"><tr>`;
                data.headers.forEach(h => tableHtml += `<th>${h}</th>`);
                tableHtml += `</tr>`;

                data.rows.forEach(row => {
                    tableHtml += `<tr>`;
                    row.forEach(cell => tableHtml += `<td>${cell !== null ? cell : ''}</td>`);
                    tableHtml += `</tr>`;
                });
                tableHtml += `</table></div>`;

                botHtml += tableHtml;
                appendMessage(botHtml, 'gpb-bot-msg', true);
            } else {
                appendMessage('Ошибка обработки: ' + (data.error || 'Неизвестная ошибка'), 'gpb-bot-msg');
            }
        } catch (err) {
            if (loadingMsg.parentNode) msgContainer.removeChild(loadingMsg);
            appendMessage('Не удалось связаться с ИИ-сервером на Windows. Проверьте сеть Tailscale и порт 5000.', 'gpb-bot-msg');
        }
    }

    sendBtn.onclick = sendQuery;
    inputField.onkeydown = (e) => {
        if (e.key === 'Enter') sendQuery();
    };

    function appendMessage(content, className, isHtml = false) {
        const msg = document.createElement('div');
        msg.className = `gpb-msg ${className}`;
        if (isHtml) msg.innerHTML = content;
        else msg.innerText = content;
        msgContainer.appendChild(msg);
        msgContainer.scrollTop = msgContainer.scrollHeight;
        return msg;
    }
})();