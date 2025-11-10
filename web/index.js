const noMessagePrompt = document.getElementById('no-message');
const chatContainer = document.getElementById('chat-container');
const body = document.body;

const OPEN_CODE_ICON = '<svg xmlns="http://www.w3.org/2000/svg" height="16px" viewBox="0 -960 960 960" width="16px" fill="#5f6368"><path d="M189.06-113.3q-31 0-53.38-22.38-22.38-22.38-22.38-53.38v-581.88q0-31.06 22.38-53.49 22.38-22.43 53.38-22.43H466v75.92H189.06v581.88h581.88V-466h75.92v276.94q0 31-22.43 53.38Q802-113.3 770.94-113.3H189.06Zm201.08-223.37-52.81-53.47 380.81-380.8H532.67v-75.92h314.19v314.19h-75.92v-184.8l-380.8 380.8Z"></path></svg>';
const RESTART_ICON = '<svg xmlns="http://www.w3.org/2000/svg" height="16px" viewBox="0 -960 960 960" width="16px" fill="#5f6368"><path d="M480-100q-70.77 0-132.61-26.77-61.85-26.77-107.85-72.77-46-46-72.77-107.85Q140-369.23 140-440h60q0 117 81.5 198.5T480-160q117 0 198.5-81.5T760-440q0-117-81.5-198.5T480-720h-10.62l63.54 63.54-42.15 43.38-136.92-137.3 137.69-137.31 42.15 43.38L469.38-780H480q70.77 0 132.61 26.77 61.85 26.77 107.85 72.77 46 46 72.77 107.85Q820-510.77 820-440q0 70.77-26.77 132.61-26.77 61.85-72.77 107.85-46 46-107.85 72.77Q550.77-100 480-100Z"/></svg>';

let messageCount = 0;
let lastUserScrollTime = Date.now();

const canConnectToVsCode = typeof acquireVsCodeApi === 'function';
if (canConnectToVsCode) {
    window.vscode = acquireVsCodeApi();
}

body.addEventListener('wheel', () => {
    lastUserScrollTime = Date.now();
}, { passive: true });

body.addEventListener('mousedown', () => {
    lastUserScrollTime = Date.now();
});

function maybeAutoScroll() {
    if (Date.now() - lastUserScrollTime > 3000) {
        body.scrollTo({
            top: body.scrollHeight,
            behavior: 'smooth'
        });
    }
}

function createMessageContent(message, isHtml) {
    const messageContentElement = document.createElement('div');
    messageContentElement.className = 'message-content';
    if (isHtml) {
        messageContentElement.innerHTML = message;
    } else {
        messageContentElement.textContent = message;
    }
    return messageContentElement;
}

function capitalize(label) {
    if (!label) {
        return '';
    }
    return label[0].toUpperCase() + label.substring(1);
}

function addMessage(message, sender, options = {}) {
    const {
        raw = '',
        isHtml = false,
        senderType,
        extraClasses = [],
        enhance = true
    } = options;

    const messageContentElement = createMessageContent(message, isHtml);

    const messageElement = document.createElement('div');
    messageElement.appendChild(messageContentElement);
    messageElement.dataset.raw = raw ?? '';

    const classNames = ['message', sender, ...extraClasses];
    messageElement.className = classNames.filter(Boolean).join(' ');

    const messageHeader = document.createElement('div');
    messageHeader.className = 'message-header';
    const label = senderType ?? sender;
    messageHeader.textContent = capitalize(label);

    chatContainer.appendChild(messageHeader);
    chatContainer.appendChild(messageElement);

    messageElement.index = messageCount;

    if (enhance) {
        enhanceMessageElement(messageElement);
    }

    maybeAutoScroll();
    return messageElement;
}

function enhanceMessageElement(messageElement) {
    const codeBlocks = messageElement.querySelectorAll('pre code');
    codeBlocks.forEach((block) => {
        block.querySelectorAll('.open-code-button, .restart-from-here-button').forEach((btn) => btn.remove());
        hljs.highlightElement(block);
        attachCodeBlockActions(block, messageElement);
    });

    messageElement.querySelectorAll('code').forEach((inlineCode) => {
        if (inlineCode.parentElement?.tagName.toLowerCase() !== 'pre') {
            hljs.highlightElement(inlineCode);
        }
    });
}

function attachCodeBlockActions(block, messageElement) {
    const openButton = createIconButton('open-code-button', 'Open', OPEN_CODE_ICON);
    openButton.onclick = (event) => {
        event.stopPropagation();
        const lang = detectLanguage(block);
        window.vscode?.postMessage({ cmd: 'open-code', content: block.textContent, lang });
    };

    const restartButton = createIconButton('restart-from-here-button', 'Restart with this', RESTART_ICON);
    restartButton.onclick = (event) => {
        event.stopPropagation();
        if (typeof messageElement.index === 'number') {
            window.vscode?.postMessage({ cmd: 'restart-session', number: messageElement.index });
        }
    };

    block.appendChild(openButton);
    block.appendChild(restartButton);

    block.onmouseenter = () => toggleActionButtons(block, true);
    block.onmouseleave = () => toggleActionButtons(block, false);
}

function createIconButton(className, title, icon) {
    const button = document.createElement('button');
    button.className = className;
    button.title = title;
    button.innerHTML = icon;
    return button;
}

function toggleActionButtons(block, visible) {
    block.querySelectorAll('.open-code-button, .restart-from-here-button').forEach((button) => {
        button.classList.toggle('show', visible);
    });
}

function detectLanguage(block) {
    for (const cls of block.classList) {
        if (cls.startsWith('language-')) {
            return cls.substring('language-'.length);
        }
    }
    return undefined;
}

function showTypingAnimation(sender) {
    addMessage('<div><span></span><span></span><span></span></div>', sender, {
        isHtml: true,
        senderType: sender,
        extraClasses: ['typing'],
        enhance: false
    });
}

function completeTypingAnimation(message, sender, options = {}) {
    const typingElement = document.querySelector('.message.typing');
    if (!typingElement) {
        return undefined;
    }

    typingElement.className = ['message', sender].join(' ').trim();
    typingElement.dataset.raw = options.raw ?? '';
    typingElement.innerHTML = '';

    const messageContentElement = createMessageContent(message, options.isHtml ?? false);
    typingElement.appendChild(messageContentElement);

    if (options.enhance !== false) {
        enhanceMessageElement(typingElement);
    }

    typingElement.index = messageCount;
    maybeAutoScroll();
    return typingElement;
}

function removeTypingAnimation() {
    const typingElement = document.querySelector('.message.typing');
    if (typingElement) {
        const header = typingElement.previousSibling;
        if (header && header.classList?.contains('message-header')) {
            chatContainer.removeChild(header);
        }
        chatContainer.removeChild(typingElement);
    }
}

window.addEventListener('message', (event) => {
    const msg = event.data;
    if (msg?.role && msg?.content) {
        noMessagePrompt.style.display = 'none';

        const waitSuffix = '-wait';
        const isWaiting = msg.role.endsWith(waitSuffix);
        const senderRole = isWaiting ? msg.role.slice(0, -waitSuffix.length) : msg.role;

        if (isWaiting) {
            showTypingAnimation(senderRole);
            return;
        }

        const rawContent = typeof msg.raw === 'string' ? msg.raw : msg.content;
        const messageElement =
            completeTypingAnimation(msg.content, senderRole, { raw: rawContent, isHtml: true }) ??
            addMessage(msg.content, senderRole, {
                raw: rawContent,
                isHtml: true,
                senderType: msg.senderType ?? senderRole
            });

        if (messageElement) {
            messageCount += 1;
        }
    } else if (msg?.cmd) {
        if (msg.cmd === 'error') {
            console.error('[IntentionTest] Webview error message received:', msg);
        } else if (msg.cmd === 'clear') {
            const targetCount = msg.toIndex ?? 0;
            messageCount = targetCount;
            while (chatContainer.children.length > 2 * targetCount) {
                chatContainer.removeChild(chatContainer.lastChild);
            }
            if (chatContainer.children.length === 0) {
                noMessagePrompt.style.display = 'block';
            }
        }
    }
});
