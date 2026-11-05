# Ricominciamo — Feed RSS personale

Feed RSS non ufficiale del podcast *Ricominciamo* di Mattia Feltri per Quotidiano Nazionale.

## Funzionamento

Lo script legge la struttura `application/ld+json` / `ItemList` dalla pagina https://www.quotidiano.net/podcast/ricominciamo, segue le pagine delle nuove puntate ed estrae l'indirizzo MP3 da `article-audio[data-url]`. Usa gli URL originali `traffic.megaphone.fm`, non quelli reindirizzati con chiave temporanea, e conserva le puntate presenti nel feed.

## Installazione

1. Crea un repository GitHub e carica i file.
2. Verifica che il branch principale si chiami `main` e abilita GitHub Pages dalla root di `main`.
3. Avvia manualmente **Aggiorna Feed Ricominciamo** da GitHub Actions e verifica `feed.xml`.
4. Soltanto dopo il test configura un cronjob `POST` su cron-job.org che chiami il workflow con `{"ref":"main"}` e un token limitato al repository.

## Limiti da verificare

- Il codice è stato predisposto dai frammenti HTML forniti dall'utente, ma non è stato collaudato con richieste live a QN (l'accesso di rete da questo ambiente è indisponibile).
- Attualmente la pagina elenca un solo episodio. Verificare, con i prossimi episodi, che l'`ItemList` li contenga tutti e che QN non usi paginazione.
- Non è stato individuato un feed RSS ufficiale; se in futuro ne viene pubblicato uno, è preferibile adottarlo.
