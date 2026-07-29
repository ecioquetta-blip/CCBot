🤖 CCBot – Bot de Backup de Grupos com Tópicos (Telegram)
O CCBot é um bot para Telegram que faz backup automático de grupos com tópicos (fóruns). Ele copia mensagens, edições, fixações e gerencia rotas de forma inteligente, tudo em português.

✨ Funcionalidades

✅ Cópia automática – qualquer mensagem enviada em um tópico de origem é copiada instantaneamente para o tópico de destino.

✅ Espelhamento automático – ao ativar o espelhamento, novos tópicos criados no grupo de origem são automaticamente criados no destino e já viram rotas.

✅ Edição com formatação – se você editar uma mensagem no grupo de origem, a cópia é atualizada preservando negrito, itálico, links, etc.

✅ Fixação automática – ao fixar uma mensagem no grupo de origem, a cópia também é fixada no destino.

✅ Nomes de rotas – dê nomes personalizados para suas rotas (ex.: "Biblioteca", "Lançamentos") e veja no /listar.

✅ Apelidos de tópicos – caso o bot não consiga obter o nome real do tópico, você pode definir um apelido manualmente.

✅ Remoção automática de rotas órfãs – se um tópico for deletado, a rota correspondente é removida automaticamente (evita erros).

✅ Notificações ao dono – erros de cópia ou edição são enviados apenas para você no privado, sem poluir os grupos.

✅ Comandos pessoais – cada administrador vê apenas as próprias rotas, mas o dono pode visualizar todas.

✅ Log de falhas – erros são registrados no arquivo falhas.log para depuração.

✅ Banco de dados leve – tudo salvo localmente no arquivo auto_forward.db (SQLite).

📋 Pré‑requisitos
Python 3.8 ou superior.

Biblioteca python-telegram-bot versão 20.x.

Um bot criado no Telegram (via @BotFather).

Seu ID de usuário do Telegram (obtenha com @userinfobot).

🛠️ Instalação
Clone ou baixe este repositório (ou apenas o arquivo ccbot.py e este README).

Instale a biblioteca necessária:

bash
pip install python-telegram-bot
Crie um bot no @BotFather:

Envie /newbot e siga as instruções.

Guarde o token (ex.: 123456:ABC-DEF...).

Obtenha seu ID de usuário:

Converse com @userinfobot e ele retornará um número como 822739234.

⚙️ Configuração
Abra o arquivo ccbot.py e edite as duas primeiras variáveis no topo:

python
DONO_ID = 123456789          # Substitua pelo seu ID
TOKEN   = "SEU_TOKEN_AQUI"   # Substitua pelo token do bot
Você também pode ajustar o intervalo de verificação de tópicos deletados (opcional):

python
VERIFICACAO_ORFAS = 600   # em segundos (0 = desativado)
🚀 Execução
No terminal, dentro da pasta onde está o arquivo ccbot.py:

bash
python ccbot.py
Se tudo estiver correto, você verá a mensagem:

text
🤖 Bot rodando com verificação de tópicos deletados!
📚 Comandos
Comando	Descrição
/start	Lista todos os comandos disponíveis.
/copiar <tópico_origem> <id_destino> [tópico_destino] [nome]	Cria uma nova rota. Ex.: /copiar 29853 -1003884054457 5879 Biblioteca
/listar	Mostra suas rotas ativas.
/parar <tópico_origem>	Remove uma rota.
/apagartodas	Apaga todas as suas rotas (com confirmação).
/status	Exibe estatísticas (número de rotas, mensagens copiadas, falhas).
/apelidar <id_tópico> <nome>	Define um nome personalizado para um tópico (ex.: /apelidar 29853 Vendas).
/nomear_rota <tópico_origem> <nome>	Dá um nome a uma rota já existente.
/espelhar <id_origem> <id_destino>	Ativa o espelhamento automático de novos tópicos.
/pararespelho <id_origem> <id_destino>	Desativa o espelhamento.
/listarespelhos	Lista seus espelhamentos ativos.
/meusgrupos	(Apenas dono) Mostra todos os grupos onde o bot está e teve atividade.
Importante: use geral ou 0 quando o tópico for o "Geral" (tópico principal).

🔐 Permissões necessárias
O bot precisa ser administrador nos grupos de origem e de destino.

Em grupos com tópicos (fóruns), a permissão "Gerenciar tópicos" deve estar ativada para que o bot consiga ler os nomes reais dos tópicos e criar novos.

Sem essa permissão, as rotas ainda funcionam, mas os nomes aparecerão como "Tópico 5879" em vez do nome real. Você pode usar /apelidar para definir manualmente.

🔧 Personalizações
Verificação de órfãos: por padrão a cada 10 minutos o bot verifica se os tópicos de origem ainda existem. Para desativar, mude VERIFICACAO_ORFAS = 0 no código.

Intervalo entre cópias: é de 2 segundos para evitar flood. Você pode alterar dentro da função auto_forward (procure por await asyncio.sleep(2)).

Limpeza do banco: registros de vínculo de mensagens com mais de 60 dias são apagados automaticamente.

❓ Resolução de problemas
Problema	Solução
“Erro ao listar tópicos: Not Found”	O bot não tem a permissão "Gerenciar tópicos" no grupo. Ative‑a nas configurações de administrador.
As rotas não aparecem no /listar	Pode ser que você tenha rotas antigas sem dono (user_id=0). O dono vê todas; outros usuários só veem as próprias. Use o script corrigir_rotas.py se necessário (veja abaixo).
Mensagens editadas não atualizam no destino	O bot só edita mensagens copiadas após a criação da rota. Mensagens antigas não são afetadas.
“Flood control exceeded”	O Telegram limita a velocidade de envio. O bot já trata flood automaticamente, mas se ocorrer com frequência, aumente o intervalo de pausa (2 segundos).

🧹 Script auxiliar (rotas órfãs)
Se você atualizou de uma versão antiga (sem identificação de usuário), pode usar o script corrigir_rotas.py para atribuir as rotas sem dono a um usuário específico. Peça ao administrador do bot que forneça esse script se necessário.

📄 Licença
Este projeto é livre para uso pessoal e pode ser compartilhado com amigos. Sinta‑se à vontade para modificar e adaptar como quiser.

OBS. no momento ele não consegue identificar o nome do tópico sozinho, é necessario adcionar um apelido.
