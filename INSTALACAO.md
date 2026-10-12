# Ícone e instalação — Passagem de Turno ADIMAX

## Configuração entregue

- Logo refinado a partir da opção escolhida, em `static/logo.png`.
- Ícones quadrados `icon-192.png` e `icon-512.png`, com fundo azul-marinho.
- `favicon.png` (64 px) utilizado por `st.set_page_config`, e `favicon.ico` com 16, 32, 48 e 64 px.
- `apple-touch-icon.png` (180 px), preparado para integração na página principal.
- Servidor de arquivos estáticos habilitado em `.streamlit/config.toml`.
- Orientações para adicionar à tela inicial na barra lateral do app.
- Manifest preparado em `static/manifest.json`, para um app hospedado na raiz do domínio.

O arquivo principal continua sendo `app.py`. Não houve alteração das regras operacionais ou do banco.

## No Streamlit Community Cloud

Após publicar o commit, o favicon e o logo ficam disponíveis no app. Os arquivos PNG e JSON são servidos em `/app/static/`. As opções de adicionar à tela inicial ou instalar uma página variam por navegador; podem criar apenas um atalho, sem garantir o ícone ADIMAX.

**O manifest preparado não está associado ao documento principal. Esta entrega não ativa uma PWA completa nem um botão automático de instalação.** Streamlit não oferece, em `st.set_page_config`, a configuração de manifest ou apple-touch-icon. Componentes HTML isolados não são uma integração confiável com o documento principal.

## Para instalação com nome e ícones próprios

É necessário controlar a página principal, por exemplo em uma hospedagem própria com proxy HTTPS e integração do HTML. No `<head>` do documento principal, incluir:

```html
<link rel="manifest" href="/app/static/manifest.json">
<link rel="apple-touch-icon" href="/app/static/apple-touch-icon.png">
<meta name="theme-color" content="#031b38">
```

Essa configuração pertence à hospedagem/documento principal; colar o trecho em `st.markdown` ou em um iframe não conclui a integração. O proxy deve preservar as conexões WebSocket do Streamlit. Se o app for publicado em um subcaminho, ajustar `id`, `scope`, `start_url`, URLs dos ícones e links ao prefixo real.

Para comportamento offline, é necessário projetar e registrar um service worker no mesmo domínio, com escopo adequado e JavaScript servido com MIME correto. O servidor estático do Streamlit serve `.js` como texto e envia `nosniff`; portanto ele não é uma solução direta para hospedar esse worker. Um service worker não é requisito universal de instalação nos navegadores atuais, mas é necessário para implementar uma experiência offline controlada.

O app atual depende de Streamlit, WebSocket e PostgreSQL. Instalá-lo **não permite consultar ou salvar passagens sem internet**. Um modo offline exigiria desenvolvimento adicional, inclusive sincronização. Evitar cache de registros operacionais e respostas autenticadas.

## Validação após publicação

1. Confirmar favicon e logo no app; atualizar o cache do navegador se necessário.
2. Abrir `/app/static/icon-192.png`, `/app/static/icon-512.png` e `/app/static/manifest.json` no domínio publicado.
3. Após a integração adicional, conferir no painel Application do navegador se o manifest está associado ao documento principal e se os ícones e `start_url` carregam.
4. Instalar e abrir pelo ícone em Android, iOS e computador, verificando navegação, reconexão e salvamento online.

## Referências

- [Streamlit: arquivos estáticos](https://docs.streamlit.io/develop/concepts/configuration/serving-static-files)
- [Streamlit: título e favicon](https://docs.streamlit.io/develop/api-reference/configuration/st.set_page_config)
- [MDN: instalação de PWAs](https://developer.mozilla.org/en-US/docs/Web/Progressive_web_apps/Guides/Making_PWAs_installable)

## Origem visual

Refinamento com a ferramenta integrada imagegen, usando a imagem escolhida como referência. Instrução utilizada: preservar os dois integrantes de capacete, checklist, setas, textos PASSAGEM DE TURNO e ADIMAX e paleta azul-marinho/branco/laranja; limpar contornos, remover margem externa e sombra e preencher o quadrado com azul-marinho. Os tamanhos finais foram derivados do mesmo arquivo para manter consistência.
