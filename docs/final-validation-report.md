# Историческая проверка операционного TODO

**Срез:** `research-operational-2026-09-26`. **Дата:** 26.09.2026.
**Итог на указанную дату:** 43/43 операционных решений; научный шлюз `G0_REVISE`.

Это завершённый исторический операционный срез. После повторного открытия
STOP-зависимых пунктов текущий счётчик и манифест отличаются; этот отчёт не
удостоверяет новое научное закрытие.

На момент среза совпадали SHA-256 49 файлов (канонические JSON верхнего уровня
`data/` и `TODO.md`); общий хеш набора был
`149360605ae5f1d8d37cdd70c9740d692292ef10e1fc235ea5b8b933316ff0d5`.
Текущий [`release-manifest.json`](../data/release-manifest.json) пересчитывается
для нового состояния и не является манифестом прежних 43/43.

## Проверки

| Команда | Результат |
| --- | --- |
| `scripts/check.ps1` | Успешно: `researchctl validate` — 0 ошибок и предупреждений; Ruff — успешно; pytest — 68 passed, 1 warning. |
| `uv run researchctl novelty-check` | Успешно; шлюз `G0_REVISE`, 15 неранжированных вариантов, `STOP-UNSATURATED`. |
| `uv run pytest tests/test_mcp.py::test_mcp_stdio_transport_smoke -q` | Успешно: 1 passed. |
| `git diff --check` | Успешно; только сообщения Git о преобразовании LF/CRLF в рабочем дереве. |
| Сверка манифеста SHA-256 | Все перечисленные файлы и общий хеш совпадают; TODO содержит 43/43 отмеченных пункта. |

## Научные и внешние ограничения

- Четыре обработанные VNC-матрицы не имеют подтверждённой точной upstream lineage; их нельзя использовать как воспроизводимый вход H1 без нового манифеста.
- Проверенные открытые маршруты не дали пригодного набора с пациентской связкой ECAP и исхода. `STOP-H3-A` не доказывает отсутствия такого набора вообще и не разрешает клинический вывод.
- Поиск prior art не достиг насыщения. `STOP-UNSATURATED` запрещает вывод об отсутствии прямого аналога, новизне, приоритете или патентоспособности.
- Авторские подписи, доступ от владельцев данных и решение научного руководителя не получены. Предложенный научный паспорт и экспериментальные протоколы условны; `GO` не установлен.

На дату отчёта Pi создал черновые файлы в `data/ns06-queries-2026-09-27/`;
они не входили в канонический снимок и не использовались как доказательство.
В текущем рабочем дереве эта папка отсутствует; её исчезновение не считается
доказательством выполнения отдельной научной проверки.

## Текущий научный срез 26.09.2026

Текущий `TODO.md` содержит 17 закрытых и 26 открытых научных пунктов из 43.
Операционные STOP сохранены с локаторами, но не засчитаны как выполнение
вновь открытых научных критериев. Шлюз — `G0_REVISE`.
`data/release-manifest.json` теперь имеет ID `research-scientific-2026-09-27`:
49 проверенных файлов, общий SHA-256
`1363b02abafdd36e9efb984b49c0ca91c5ab7d2b10d331a271b12309f10423bf`.
Все файловые SHA-256 и агрегат независимо пересчитаны; расхождений нет.

Реестр содержит 222 канонические карточки. `S807` фиксирует стохастические
сенсорные каскады на FlyWire v783; `S808` — вкусовую схему FlyWire v630 с
предсказанной LIF-активностью. Обе карточки опубликованы через stage/publish
после проверки DOI, дублей и полных первичных текстов. Снимки отката созданы
в `.work/research-snapshots/`; staging-кандидаты `S807`/`S808` удалены.

Матрица содержит 159 положительных строк; 159/159 строк адресно сверены
по первичным маршрутам. В журнале EVD-03 есть адресные проверки либо узкие
ограничения для всех ранее учтённых ID, включая официальный PDF S189, но это
не полный смысловой sign-off матрицы. Карточка `S075` согласована с матрицей
проверенной партией `r4-correction-002`; `S017` в матрице
ограничен DOI-идентичностью из-за недоступного первичного abstract. Точная
upstream lineage четырёх матриц S740, пригодный
открытый связанный ECAP/outcome-набор и насыщение prior art не установлены.
Аудит границ переноса охватывает 159/159 текстовых строк матрицы и 222/222
текущих карточек в ограниченном текстовом проходе с явным списком ID и
хешем реестра. Это не полный семантический sign-off первичных текстов;
исторический список 204 карточек по-прежнему не восстановлен.
Повторная проверка полного XML `S015` восстановила подтверждённые 65 участников
с субъектным разбиением и отдельную группу из 15 человек того же протокола;
это не внешняя клиническая проверка.
Новые разделы O и P журнала EVD-03 охватывают ещё 29 строк. У `S191` результат
46,76% ограничен валидационной частью AI4PAIN; у `S025` TENS — подгруппа
обучающего исследования, а не независимая когорта. По `S045` подробности
недоступной рукописи сняты из проверенного вывода. В карточке `S253`
исправлен размер исходной модели по странице владельца; у `S025` полные
авторы сверены с регистрацией DOI, репрезентативная карточка C10 и отчёт
полноты синхронизированы. Это исторический срез 81/159: остальные 78 индексов позже получили ограниченные адресные решения в разделах Q–U; пробелы полного текста и авторская приёмка остаются открытыми.
Повторная проверка открытых ECAP-наборов добавила ограниченные отрицательные
диспозиции для модельных данных Figshare, свиных записей и набора Dryad
без требуемой пациентской связки. `STOP-H3-A` не подтверждает отсутствия
подходящего набора вне проверенных маршрутов. По NS-11 полный BMJ JATS для
`S755` установил порог 50% и когорту 945, а проверенная копия издательской
страницы `S762` — четыре компонента исхода и 80/20 validation; точные
модельные знаменатели и patient-disjointness остаются неизвестными.
Для всех 23 индексированных цитирований S792 записаны ограниченные
диспозиции с первичными маршрутами. Четыре — частичные аналоги переноса
моделей оценки боли, но ряд полных текстов недоступен; индекс не является
исчерпывающим. Все 86/86 цитирующих записей `S775` в сохранённом срезе
OpenAlex получили ограниченную диспозицию, но индекс не исчерпывает поиск.
`PA-04` дополнительно проверил полный текст анализа EVOKE PMID 38490687,
сохранив одну исходную когорту; `PA-06` разобрал 33 исключённые регистрации
из 458 ID после воспроизводимого отбора. Полный ручной просмотр остаётся открытым.
По NS-15 проверен полный PDF Курмукова; три текста РГБ по текущим маршрутам
недоступны для методической проверки.
Новые аналоги сбросили счётчик чистых датированных обновлений.

Проверки текущего среза: `researchctl validate` — 0 ошибок и предупреждений;
`researchctl novelty-check` — успешно, `STOP-UNSATURATED`; Ruff — успешно;
pytest — 70 passed, 1 warning; `scripts/check.ps1` — успешно;
MCP stdio smoke test — 1 passed; `git diff --check` — успешно.

Автоматические снимки публикаций перенаправлены в игнорируемое
`.work/research-snapshots/`, где сохраняются два последних; явный snapshot
пишется в `data/archive/` с отдельным ограничением для новых снимков.
Два старых каталога `pre-publish`
от 25.09 остаются в `data/archive/`: автоматическая проверка команды отклонила
их рекурсивное удаление как `blocked by policy`. Два базовых миграционных
среза сохранены. Отсутствующие 16 сырых ответов Pi не удалось сверить с
`ns06-prior-art-audit.json`; их содержимое не было принято в текущую базу.

В корне `research` остались созданные во время адресных проверок неотслеживаемые
временные `.audit_a.tmp.txt`, `.audit_b.tmp.txt`, `.audit_extract124.tmp.js`,
`.audit_rows107_132.tmp.txt` и `.tmpaudit/`. Они не входят в `data/` или
SHA-256-манифест. Автоматическая проверка отклонила команду их удаления
как `blocked by policy`; повторное удаление обходным способом не выполнялось.


## 2026-09-26 bounded evidence review update

Sections Q, R, S, T and U of `data/evd03-evidence-matrix-audit-2026-09-25.md` now assign a dated primary-source disposition to all 159/159 evidence-matrix rows. Coverage records what could be checked, including DOI-only and abstract-only rows; it is not a scientific sign-off. The S078 catalog discrepancy was corrected after the ScienceDirect Section 6, Chapter 23 contents and Crossref DOI record were found to agree on title, authors and pp. 283-297. S021 and S747 source-card statements were also narrowed to the evidence actually present in their primary records. EVD-03 remains open, as does SRC-08.

For S740, owner routes now identify candidate MANC, FANC, mCNS and BANC exports, but none proves which exact release and processed matrix were used in the four S740 inputs. Their `upstream_release` values remain `not_reported`. The Freshwater/Rosella 2025 ECAP study candidate has no baseline pain, pain relief, or function outcome in its publisher Limitations section and has only request-based data availability. It does not satisfy RES-04 or RES-05. The scientific TODO remains 17/43 with G0_REVISE; the prior 43/43 STOP-based operational count is historical.

Final checks after this update: `scripts/check.ps1` passed (`researchctl validate`: 0 errors and 0 warnings; Ruff passed; pytest 70 passed, one dependency deprecation warning). `researchctl novelty-check` passed with `STOP-UNSATURATED` and `G0_REVISE`. MCP stdio smoke test passed (1 test). `git diff --check` passed with line-ending conversion warnings only. An independent SHA-256 recomputation matched all 49 manifest entries and aggregate `be0d6dd1899604e6d3acdd2796018408d14f274422c45aa305e40739c94809d4`.

## Дополнение 27.09: источники NS-03 и маршруты S740

После сверки первичных текстов и проверки дублей через stage/dry-run/publish
добавлены `S809`–`S813` (PPK, Piezo, тепловое escape-поведение, RNAi-скрининг
и SK-канал). Текущий NS-03 содержит 32 карточки; среди отдельного списка из
28 поимённых работ 16 имеют точное DOI-совпадение, 12 получили ограниченный
первичный экран без публикации карточки. Исторический агрегат 27 остаётся
нерасшифрованным. У `S813` механически вызванный GCaMP3-ответ в препарированной
личинке отделён от rolling и теплового поведения; размеры групп из
недоступной дополнительной таблицы не выдуманы.

Дополнительные маршруты владельцев дают кандидатные экспорты MANC, mCNS,
FANC и BANC. Они не связывают точный релиз и экспортный запрос с четырьмя
матрицами Figure 2 `S740`; `upstream_release` остаётся `not_reported`.
Научные критерии `SRC-03`, `SRC-04` и зависимые пункты остаются открытыми.
Опубликованные кандидаты `balboa.json`, `piezo2012.json`, `oswald2011.json`,
`honjo2016.json` и `walcott2018.json` остаются в игнорируемом
`data/staging/inbox/`: автоматическая проверка отклонила их удаление. Они не
входят в манифест и не являются сырыми ответами Pi.

Повторные проверки `scripts/check.ps1` прошли: validate 0 ошибок/0 замечаний,
Ruff успешно, pytest 70 passed (одно предупреждение зависимости).
`researchctl novelty-check` вернул `STOP-UNSATURATED` при `G0_REVISE`;
MCP stdio smoke test — 1 passed; `git diff --check` — без ошибок.
Повторный первичный проход NS-11 от 27.09 не изменил `PA-05`: Ovid для
`S034` направил к аннотации, полные маршруты `S046`/`S762` ответили 403,
издательский JATS `S755` остался доступен без недостающих модельных полей.
Состояние зафиксировано в действующем сводном аудите.

Дополнительный адресный проход 27.09 проверил четыре открытых Mendeley/Dryad
набора для `RES-04/05`: их страницы не подтверждают связанную пару человеческого
ECAP с клиническим исходом; состав файлов Mendeley через API не был доступен
без авторизации. По `PA-03` официальный каталог SAC подтвердил только
идентичность статьи об ultra-short EDA, а ACM не отдал метод. Оба пункта
сохранили ограничения в живых аудитах без объявления насыщения или доступа.

После проверки полного авторского PDF, PubMed и дублей опубликована карточка
`S814` Imambocus et al. NS-03 содержит 33 карточки, а отдельный список
из 28 работ — 17 точных DOI-совпадений и 11 проверенных, но ещё не
опубликованных кандидатов. Оптическая активность, EM-анатомия, световое
избегание и ответ на 50 mN касание размечены раздельно. Восьми карточкам
`S797`–`S804` добавлен отдельный первичный маршрутный просмотр; для `S798`
он остаётся на уровне официальной аннотации.

Проверки после интеграции `S814` и датированных аудитов: `scripts/check.ps1`
прошёл (`validate`: 0 ошибок/0 предупреждений; Ruff успешно; pytest 70 passed,
одно предупреждение зависимости). `researchctl novelty-check` сохранил
`STOP-UNSATURATED` и `G0_REVISE`; MCP stdio smoke test — 1 passed;
`researchctl completeness` — 222 записи, 0 неразрешённых полей;
`git diff --check` — без ошибок. Независимый пересчёт подтвердил 49 SHA-256
файлов и общий хеш манифеста выше. Опубликованный кандидат `S814` и две
временные копии интеграции остались в `.work/research-candidates/`: точное
удаление файлов отклонено автоматической проверкой команды. Научный TODO
остаётся 17/43.

## Current integrated slice, 2026-09-27

This section supersedes earlier dated counts and hashes above. The scientific TODO is **17/43** and the gate is **G0_REVISE**. The earlier 43/43 STOP-based count was an operational slice and does not satisfy the reopened scientific criteria.

- `S815` was published after checking the [full author manuscript](https://pmc.ncbi.nlm.nih.gov/articles/PMC3278078/) and [PubMed PMID 22347718](https://pubmed.ncbi.nlm.nih.gov/22347718/). Its larval heat/mechanical behavior, cellular calcium and patch-clamp observations are separate; it does not provide in-vivo mdIV recording or human pain evidence.
- `S079` was corrected with reviewed batch `r5-correction-001` using the [PubMed PMID 41504676 author abstract](https://pubmed.ncbi.nlm.nih.gov/41504676/). The scoping review reports 28 publications covering 19 studies, with subjective, posture/movement and ECAP feedback classes kept separate. The publisher full text returned HTTP 403 here, so the card remains `metadata_only`; it is not a new patient-level linked dataset.
- `S816` was published after checking [bioRxiv v1 full text](https://www.biorxiv.org/content/10.64898/2026.08.22.746456v1.full): an executable adult fly LPLC2-to-Giant-Fiber looming-escape simulation with direct-hit and near-miss trajectories. It is new PA-01/NS-04 prior art, without a reported exact connectome export, live-fly validation, nociception, ECAP or clinical outcome.
- `S817` was published after checking [Frontiers full text](https://www.frontiersin.org/journals/pain-research/articles/10.3389/fpain.2025.1562099/full) and [PubMed PMID 40337527](https://pubmed.ncbi.nlm.nih.gov/40337527/). X-ITE real phasic-to-real tonic pseudo-label adaptation uses participant LOSO and 14 tonic windows per event; the original corpus has 134 people while Figure 1 says 125 in this analysis. The denominator difference is unresolved, raw data require a research request, and there is no separate external cohort. This broad partial PA-03 analogue resets the clean-refresh count to zero as of 2026-09-27; the next distinct dated pass is no earlier than 2026-09-28. It does not test synthetic-source transfer, patient clinical pain, ECAP or SCS.

- `S818` is the [Springer LNCS predecessor](https://link.springer.com/chapter/10.1007/978-3-031-37660-3_28), DOI `10.1007/978-3-031-37660-3_28`. Only publisher title, metadata and abstract are accessible: real X-ITE phasic-trained Random Forest, 14 tonic chunks and participant LOSO are verified, while exact analyzed N, sensors, labels and full method are unavailable. The card stays `verified_metadata` / `metadata_only`.
- `S819` is the [MDPI Computers predecessor](https://www.mdpi.com/2073-431X/12/4/71), DOI `10.3390/computers12040071`. An [official 19-page publisher PDF](https://mdpi-res.com/d_attachment/computers/computers-12-00071/article_deploy/computers-12-00071.pdf) was fetched with HTTP 200 via Picodex (SHA-256 `a046ad5cc95217d26e6f713552684fec5ce2d0b2b4ba0460247efb8743b0d197`) and section/page excerpts checked. It reports 125 analyzed of 134 healthy X-ITE people, nine excluded for data errors, participant LOSO, and phasic prototype-distance selection of a tonic segment. The S819 exclusion explanation does not prove S817 used exactly the same subset. S818, S819 and S817 are distinct method stages in one X-ITE research lineage, not independent replications or synthetic-source tests. This same-day backward-citation follow-up does not count as a clean later-dated saturation pass.

The current corpus has **227 canonical source cards**, 271 aliases, 43 active clusters, 109 resources and zero unexplained nullable fields. The `data/forbidden-transfer-audit-2026-09-25.json` roster hashes this 227-card state; its 223 older cards underwent the prior bounded text screen, while S816-S819 received individual five-field checks. This is not a full primary-text audit of all 227 papers.

Current gates: `scripts/check.ps1` passed (`researchctl validate`: 0 errors/0 warnings; Ruff passed; pytest **70 passed**, one dependency deprecation warning). `researchctl novelty-check` passed with `STOP-UNSATURATED` and `G0_REVISE`; `researchctl completeness` reported 225 records and zero unresolved fields; MCP stdio smoke passed (1 test). These software checks do not establish scientific novelty, clinical effect or a GO decision.

The release manifest hashes **49** current files, with aggregate SHA-256 `e61306c5ce34b2c436c477ba4ba18b460aefdf13e3a9583ae529761e7ca7967c`. Scientific blockers include S740 upstream lineage, inaccessible full methods for S088, unavailable participant-linked ECAP/outcome data, incomplete prior-art saturation, and author/supervisor decisions. All related TODO items remain open.

### Follow-up integrated slice, 2026-09-27

This subsection supersedes the preceding 227-card count, corpus hash and gate results. The scientific TODO remains **17/43**, with 26 open scientific criteria and `G0_REVISE`. No STOP-only item was reclosed.

- `S820` was published from the [Springer conference abstract](https://link.springer.com/chapter/10.1007/978-3-030-68780-9_59): real X-ITE phasic-electrical to tonic-electrical transfer with personalized k-fold, RF and DNN. The chapter full text is restricted, so participant N, exact sensor inputs, folds and numeric results are not inferred. NS-06 remains unsaturated; same-day discovery is not a later-dated clean refresh.
- `S821` was published from the [PLOS full text](https://journals.plos.org/ploscompbiol/article?id=10.1371/journal.pcbi.1013452), with the [publisher correction](https://journals.plos.org/ploscompbiol/article?id=10.1371/journal.pcbi.1013902) checked. Extended reciprocity and a semi-analytic peripheral vagus eCAP model were compared with recordings from five minipigs. This adds a physical observation-operator comparator, not fly-to-human transfer, spinal SCS validation or a pain outcome. The correction changes XML/PubMed first-author indexing only.
- Existing `S092` was rechecked against the [full eLife/PMC text](https://pmc.ncbi.nlm.nih.gov/articles/PMC12068870/): epidermal optogenetic stimulation, sensory-neuron calcium, mechanical epidermal calcium and larval behavior are separate assays. `S822` ([eLife full text](https://elifesciences.org/articles/12959)) adds local heat to Class IV extracellular firing/calcium and distinct behavior; the article estimates about 43 C at 30 mW, not a universal 47 C threshold. `S823` ([BMC full text](https://link.springer.com/article/10.1186/1471-2202-15-14)) adds UVC to mdIV firing and distinct writhing assays. The `S823` card was corrected through reviewed batch `r5-correction-s823-calibration`: UVC dosimetry is not predictive-model calibration. NS-03 has 36 named cards; Yoshino et al. 2025 remains a separately documented bioRxiv lead. SRC-04 remains open because historical bibliography coverage and SRC-03 lineage are incomplete.
- The existing `S086` evidence-matrix row now uses the [author README at a pinned commit](https://github.com/AnupKumarGupta/HCAT-Pain/blob/5571db315f6965159a11392c958e5d86defdb406/README.md) for explicitly author-reported AI4Pain results. The IEEE full text, split protocol and independent validation remain unavailable; no clinical or cross-subject conclusion is promoted.

The corpus now contains **231 canonical source cards**, 271 aliases, 43 active clusters, 109 resources and zero unresolved schema fields. DOI and exact-title scans found no duplicate for S820-S823. `data/forbidden-transfer-audit-2026-09-25.json` hashes the current 231-card roster and records bounded five-field checks; it does not claim a full primary-text review of all sources. Pi workers did not edit canonical files, and `data/` contains no raw Pi response directory. Two older pre-publish snapshots remain under `data/archive/` because earlier automatic command review blocked their deletion; the two newest automatic rollback snapshots are kept under ignored `.work/research-snapshots/`.

Final gates on this slice: `scripts/check.ps1` passed (`researchctl validate` 0 errors/0 warnings; Ruff passed; pytest **70 passed**, one dependency deprecation warning); `researchctl novelty-check` retained `STOP-UNSATURATED` and `G0_REVISE`; `researchctl completeness` resolved all fields in 231 records; MCP stdio smoke passed (1 test); `git diff --check` passed. Independent SHA-256 verification matched all **49** manifest files, TODO 17/43, the 231-card roster hash and aggregate `39e8034c3cc438ef0f7274656c89b407190901f5198cd56d121e88e3ea3107d9`. These checks do not establish novelty, clinical effect or GO.

### Additional primary-source and Picodex slice, 2026-09-27

This subsection supersedes the preceding 231-card count and manifest hash. The scientific TODO remains **17/43**, with `G0_REVISE` and 26 open scientific criteria. Fifteen bounded Picodex jobs were submitted under a workspace limit of 20: 13 reached `agent_settled` with exit 0 and no extension error; two long-running NS-03 checks were cancelled and excluded from evidence. Pi workers did not edit canonical files.

- `S824` was published from the [eLife article](https://elifesciences.org/articles/29754) and [full Europe PMC XML](https://www.ebi.ac.uk/europepmc/webservices/rest/PMC5653240/fullTextXML). Local IR heating directly evokes Class IV firing; separate larvae undergo the heat-probe rolling assay. The neural and behavioral units are distinct, and the result does not establish subjective pain or human transfer.
- `S825` was published from a [2025 archive of the original Current Biology full text](https://web.archive.org/web/20250312154123id_/https://www.cell.com/current-biology/fulltext/S0960-9822(17)30805-9) after exact DOI review. Figures 2 and 4 directly image calcium in mCSI and SNa following optogenetic C4da/mCSI activation; Figure 3 tests rolling separately. Natural noxious-stimulus-evoked spikes are not measured. NS-03 now has 38 named cards; the independent 28-work list has 19 exact DOI matches and nine screened DOI-unmatched leads. The historical 27-lead aggregate remains unreconstructable, so `SRC-04` stays open.
- Reviewed batches `r5-correction-s755-fulltext`, `r5-correction-s755-access-flag` and `r5-correction-s762-fulltext` corrected stale abstract-only source cards. [BMJ publisher JATS](https://rapm.bmj.com/content/rapm/45/2/131.source.xml) establishes the S755 50% SCS-success definition and 945/826/119 cohort counts. An [archived LWW publisher article](https://web.archive.org/web/20210930010639id_/https://journals.lww.com/pain/fulltext/2021/02000/high_dose_spinal_cord_stimulation_for_patients.23.aspx) establishes S762's four-component 12-month responder and reported 80/20 split. Neither text gives a prediction-specific complete-case N or patient-disjoint split. Live LWW access returned 403; `PA-05` remains open.
- Reviewed batch `r5-correction-s822-title` repaired the S822 title that had been set to its author list, preserving the assay and construct limits. Two further open [Zenodo SMA motor data](https://zenodo.org/records/14201209) and [Zenodo zoster-pain Table S1](https://zenodo.org/records/3263885) records have CC BY 4.0 file deposits but do not contain the required human epidural-SCS ECAP × patient pain outcome linkage. `RES-04/05` and `STOP-H3-A` remain open.

The current corpus has **233** canonical source cards, 271 aliases, 43 active clusters, 109 resources and zero unresolved schema fields. The live NS-03, NS-11, human ECAP access, search-protocol and source-card text-screen audits have been updated. No raw Pi response was placed under `data/`; the release manifest below is refreshed after the final data and TODO edits.

Final checks on this slice: `scripts/check.ps1` passed (`researchctl validate` 0 errors/0 warnings; Ruff passed; pytest **70 passed**, one dependency deprecation warning); `researchctl novelty-check` retained `STOP-UNSATURATED` and `G0_REVISE`; `researchctl completeness` resolved all fields in 233 records; MCP stdio smoke passed (1 test); `git diff --check` exited 0 with only Git line-ending conversion notices. An independent SHA-256 verifier matched all **49** manifest files, TODO **17/43**, the 233-card source roster hash and aggregate `a398da2905a631d704662afe15a365f9df2120dd8a298413d5bb981350b65354`. These software and curation gates do not establish novelty, clinical effect or GO.

## Additional scientific slice, 27 September 2026

The preceding 233-card count is historical. The current corpus has **234** canonical cards after primary review and publication of `S826` (Mohabbati 2025, DOI `10.1093/pm/pnaf058`). The six saved ClinicalTrials.gov query routes were screened across all 458 distinct NCT IDs; `NCT04687215` was resolved as a text false positive because “recapture” contains “ECAP”. This bounded route screen does not establish global trial or prior-art saturation. The Cambridge C1 accepted version was linked to IEEE document 11655613 and DOI `10.1109/mce.2026.3723599`; the distinct S088 DOI and access limitation were preserved. Four evidence-matrix rows were corrected or narrowed against primary sources (`S241`, `S099`, `S049`, `S239`). No result was promoted from an unverified Pi answer.

The Picodex workspace was saturated to its configured limit of **20 concurrent workers** in three waves. The final 20-source read-only wave yielded 18 settled responses with exit 0 and no extension errors; two overlong jobs (`S817`, `S762`) were cancelled and excluded. Independent primary review led to corrections for `S229` (source type), `S767` (paired posture denominator) and `S239` (registry enrollment versus analyzed flow). Other candidates, including `S049` and `S740`, remain pending primary reconciliation. Pi workers did not edit canonical files or place raw replies in `data/`.

`scripts/check.ps1` passed after the integrated edits (`researchctl validate`: 0 errors/0 warnings; Ruff passed; pytest **70 passed**, one dependency deprecation warning). `researchctl novelty-check` retained `STOP-UNSATURATED` and `G0_REVISE`; `researchctl completeness` resolved all fields in **234** cards; MCP stdio smoke passed (1 test); `git diff --check` exited 0 with only Git line-ending notices. Independent SHA-256 recomputation matched all **49** manifest files, TODO **17/43**, the 234-card source roster and aggregate `8d20007490bd2850b22a40549567999b975676b633f69ccdb884294fb813c6f5`. The 26 open scientific criteria and `G0_REVISE` remain in force.

## Further primary reconciliation, 27 September 2026

The preceding aggregate is historical. Sixteen read-only Picodex tasks screened separate dataset routes and matrix claims: 13 settled with exit 0 and no extension error, while three overlong jobs were cancelled and excluded. Independent primary checks added a CC0 Dryad SCS imaging near match and two OSF EEG near matches to the human-access audit; none supplies the required ECAP plus linked clinical outcome. NCT04319887 now anchors `S237`'s ECAP dose ratio to 208 twelve-month completers. `S049` now records held-animal within-study validation, `S740` separates four-dataset front-leg comparisons from full-MANC six-leg results, and `S138` follows the publisher final PDF's conceptual wording. Cluster representative copies and completeness counters were synchronized with the revised cards. `RES-04/05`, `EVD-03` and `SRC-03` remain open; `G0_REVISE` is unchanged.

The new manifest contains **49** files, **234** cards and TODO **17/43**, with aggregate SHA-256 `af21323d3aba99214a94c150b5ceb93dc2cfc55f61f65030bc622da3224c9cc0`. The checks for this final slice are recorded after execution below.

Final-slice checks passed: `scripts/check.ps1` ran `researchctl validate` with 0 errors/0 warnings, Ruff with no findings, and pytest with **70 passed** (one dependency deprecation warning). `researchctl completeness` found 8,424 resolved fields and 0 unresolved across 234 cards. `researchctl novelty-check` retained `STOP-UNSATURATED`/`G0_REVISE`; MCP stdio smoke passed (1 test); `git diff --check` exited 0 with line-ending notices only. The independent verifier matched all 49 hashes, the 234-card roster and TODO 17/43 to the manifest aggregate above. These software gates do not establish scientific completion, clinical effect, or GO.

## Picodex primary-review slice, 27 September 2026

The earlier 234-card count and hashes are historical. Bounded Picodex checks filled the configured **20/20 concurrent-worker** limit in several waves. The overlong tasks were cancelled and their partial answers excluded; Pi workers did not edit canonical files or place raw responses in `data/`. Every promoted claim below was checked against a primary source by the integrating agent.

Two source cards were published through stage, review and publish: `S827` ([eLife 76574](https://elifesciences.org/articles/76574)) measures mechanically evoked c4da calcium and reports a separate larval rolling assay; `S828` ([eLife 85760](https://elifesciences.org/articles/85760)) measures thermally evoked Goro calcium and reports separate protective behavior. NS-03 has **40** named cards, and the corpus has **236** canonical source cards. These assays do not establish subjective pain, a human ECAP mapping or clinical response. The historical NS-03 bibliography and `SRC-03` lineage remain unresolved, so `SRC-04` stays open.

The [IEEE publisher abstract for S088](https://ieeexplore.ieee.org/abstract/document/11606012) now supports an abstract-level method description; the full paper, cohort/split details and numeric results remain unavailable. The [S149 PubMed record](https://pubmed.ncbi.nlm.nih.gov/42630337/) confirms its identifiers. The S791 OpenAlex forward-citation set has 26 indexed works, nine overlapping the 23 S792 citations; the 17-item set difference remains a bounded lead set after duplicate review, not completed prior-art saturation. Matrix rows were corrected against primary locators, including the `S766` P2-N1 comparison: clinical 200 μV, model 216 μV. These changes leave `EVD-03` and `PA-03` open.

Final checks after integration: `scripts/check.ps1` passed (`researchctl validate`: 0 errors, 0 warnings; Ruff passed; pytest **70 passed**, one dependency deprecation warning). `researchctl completeness` found **8,496** resolved fields and zero unresolved across 236 cards. `researchctl novelty-check` retained `STOP-UNSATURATED` and `G0_REVISE`; MCP stdio smoke passed (1 test); `git diff --check` passed with line-ending notices only. Independent SHA-256 verification matched all **49** manifest files, the 236-card roster, TODO **17/43**, and aggregate `58bce285855644642dd4aa25cef9c8b60d6a5b92fbfda3dc050b53014e9d40fb`. The remaining 26 scientific criteria require additional primary evidence, data access, citation saturation or author/supervisor decisions; no GO or clinical effect follows from these checks.

### S791 forward-citation wave, 27 September 2026

The preceding aggregate is historical. Two Codex coordinators submitted ten bounded Pi jobs each and the root submitted three more as slots freed; the shared Picodex workspace reached **20/20** active. Eight PA jobs and one S762 access job completed with `agent_settled`, exit 0 and no extension errors. Eight other SRC/RES jobs and two PA jobs exceeded the time budget and were cancelled; their partial answers were excluded. One MANC receipt returned `unknown jobId` on status/cancel and produced no usable evidence. The root's three follow-up jobs settled successfully. Pi workers did not edit canonical files.

The 17-item S791-only OpenAlex difference is now dispositioned in `data/ns06-prior-art-audit.json`: three S792/version-family records and 14 third-party records. Two of the third-party Pi checks timed out; the root independently resolved them from an [official Linköping University dissertation](https://liu.diva-portal.org/smash/get/diva2%3A1800798/FULLTEXT02.pdf) and the [EmoPain authors' project page](https://pr.ai.vn/publication/emopain_fg20/). The official [MVA conference paper](https://www.mva-org.jp/Proceedings/2021/papers/P3-5.pdf) establishes a synthetic GTA5-to-real Cityscapes segmentation method without a pain target; the [Nature article](https://www.nature.com/articles/s41598-025-04552-w) describes real UNBC-to-BioVid pain assessment without a synthetic source. These are bounded method distinctions. The [Springer abstract for Florea et al.](https://link.springer.com/chapter/10.1007/978-3-319-16199-0_54), discovered via another citation, adds an earlier emotion-to-facial-pain representation-transfer lead whose full method is restricted. S762's additional repository routes did not expose a model denominator, patient-disjoint split or ECAP predictor. `PA-03`, `PA-05` and the broader citation-saturation criterion remain open.

After this audit/TODO edit, `researchctl validate` passed with zero errors and warnings; `researchctl novelty-check` retained `STOP-UNSATURATED`/`G0_REVISE`; `git diff --check` passed. The independent verifier matched all **49** manifest entries, **236** sources, TODO **17/43** and the current aggregate SHA-256 `4ed1c5c597073fed5b85ff368657ded6f2e38a6834aa27e501413c84fcdbf9f0`. The earlier full `scripts/check.ps1` run on this 236-card slice passed 70 tests and Ruff; only research audit text and the manifest changed afterward.


## S829 primary-text integration, 27 September 2026

The current corpus contains **237 canonical source cards**. S829 (Florea et al., 2015) was checked against the official Springer chapter page and publisher PDF. Sections 4 and 6.1-6.2 (pp. 782-787) describe representation transfer from unlabeled Cohn-Kanade emotion faces to UNBC-McMaster facial-action pain-score estimation and leave-one-person-out evaluation across 25 participants; Section 7 (p. 788) discusses limitations. The target is not patient self-report or a clinical outcome, and the paper reports no ECAP or SCS measure. The source remains a bounded earlier analogue lead; its discovery does not satisfy the later-dated prior-art saturation criterion or close PA-03.

The five-field card-level text-screen roster now includes S829 and hashes the current `data/records.json` bytes as `27e17dd2bb8089c4e37df5092e1df0be5e49c582e5c8150b51e2ec485c2606e4`. Its 237-card scope remains a card-level construct screen, not a full primary-text review. `researchctl validate` passed with zero errors and warnings; `git diff --check` passed.

## Current integration and workspace hygiene, 27 September 2026

The dated EVD-03 batch narrowed four matrix rows (`S039`, `S082`, `S017`, `S195`) to checked publisher abstracts or a primary JATS letter. The PA-04 audit now records the primary S765 reference to Chakravarthy et al. (PMID 35041590) and the indexed EVOKE-to-S239 citation edge, keeping sensing, stimulation experience and analgesia separate. Their unresolved methods and citation chains remain open in TODO. A later S088 Pi recheck was interrupted before `agent_settled`; its scratch output was not promoted to the evidence base.

Superproject scratch entries were moved to ignored `research/.work/root-scratch-2026-09-27/`, and project-root scratch entries to `research/.work/research-root-scratch-2026-09-27/`. New Picodex prompts require one `.work/pi-workers/<bridge-id>/<task-id>/` directory per worker with `result.md`, optional `raw/`, and optional `logs/`. No new untracked scratch file remained in the superproject root at this check.

At this intermediate slice, the release manifest contained **49** file hashes with aggregate SHA-256 `bdc9127522e1fd365d817c0e08fa187d40264f794e58b96981c5decb4ee6bb9e`. Independent recomputation matched all entries and the 237-card construct-screen roster. TODO remained **17/43 closed** and the scientific gate remained `G0_REVISE`. `scripts/check.ps1` passed (237 sources, zero validation errors/warnings, Ruff passed, 70 pytest passed with one Starlette deprecation warning); `researchctl novelty-check` retained `STOP-UNSATURATED`; the focused MCP test passed 5/5; `git diff --check` passed.

## Picodex follow-up and current manifest, 27 September 2026

Three separate Codex coordinators issued ten Pi tasks each for EVD-03, PA-04 and RES-04/05. The shared workspace reached its configured **20/20** running limit without producing new untracked scratch files at `R:\Aspa`. Each task has a folder under `research/.work/pi-workers/<bridge-id>/<task-id>/` and a `result.md`; each coordinator has a run-level `jobs.json` receipt registry. The Picodex skill now requires immediate receipt capture, fixed result sections, and a status stub for interrupted work.

EVD-03 gained one independently verified source-level correction for `S030` from full Europe PMC JATS. Eight other EVD tasks failed, timed out or were cancelled without accepted findings; `S088` settled but its additional figure detail could not be independently retrieved, so its matrix row was not changed. PA-04 recorded bounded citation edges and a new rat SNI dose-response lead (PMID 42055600); these do not establish human analgesia or complete saturation. RES-04/05 added an aggregate-only EVOKE supplement check, corrected its article DOI, and excluded two further open near-matches (OpenNeuro `ds005691`, Zenodo `5509670`) because the required participant-linked ECAP/pain outcome pair was not documented. One RES worker's job/thread receipt was lost; its saved output was excluded from integration. `STOP-H3-A`, the PA saturation gap, and all related scientific TODO items remain open.

Automatic approval review rejected the EVD coordinator's `Remove-Item -LiteralPath ... -Recurse -Force` cleanup with `rejected: blocked by policy`; it gave no more specific reason. No deletion was attempted by another route. Eight unsuccessful EVD task folders retain **404** unreviewed raw files in ignored `.work/pi-workers/490e92b0-b73a-4cda-9e24-c8d11b623c09/`; their status stubs and `jobs.json` identify the exact paths. None of those files is in `research/data` or in the release manifest.

The current release manifest hashes **49** files with aggregate SHA-256 `0fe3df24e5c6367a9a83da252f0dc068566d87fcece9b43fe92193f4ba20297b`. Independent recomputation matched every file and the 237-card roster; TODO has **17/43** checked, and the scientific gate remains `G0_REVISE`. `scripts/check.ps1` passed (Ruff, 70 pytest, zero researchctl validation errors/warnings); `researchctl novelty-check` retained `STOP-UNSATURATED`; focused MCP tests passed 5/5; `git diff --check` passed. One Starlette dependency deprecation warning remains in pytest.

## Bounded follow-up and worker artifact correction, 27 September 2026

Three Codex coordinators and the root submitted 18 Picodex tasks across S740 lineage, EVD-03, NS-06, RES-04/05, PA-04 and SRC-04. The observed shared peak was **17/20** active Pi processes. Eight jobs completed with `agent_settled`; ten overlong jobs were cancelled and their partial outputs excluded. Each task has a structured folder and `result.md` under ignored `.work/pi-workers/<bridge-id>/<task-id>/`; run-level `jobs.json` files retain receipts and terminal statuses. The cancelled EVD and PA tasks retain unreviewed raw artifacts in `.work`, outside canonical `data/` and the release manifest. The prior automatic cleanup rejection still applies; no alternative deletion route was attempted.

A worker shell redirection created an untracked `R:\Aspa\nul` containing a failed `cd` diagnostic. It was moved into `research/.work/root-scratch-2026-09-27/`; the superproject root again has no untracked scratch file. Both the research and Picodex skills now prohibit bare `>nul`/`>NUL` and direct diagnostics to each worker's `logs/` folder. Coordinators were also told to use a shell-valid quoted project path.

The official Harvard Dataverse, G-Node GIN and EBRAINS catalog routes gave bounded negative results for a public human epidural-SCS ECAP recording linked by patient ID to chronic-pain outcome. The [Dataverse exact Boolean API query](https://dataverse.harvard.edu/api/search?q=%22ECAP%22%20AND%20%22spinal%20cord%20stimulation%22&type=dataset&per_page=15) returned zero; four exact spinal-cord-stimulation metadata hits described other constructs. The [GIN ECAP search](https://gin.g-node.org/api/v1/repos/search?q=ECAP&limit=50) returned five records, including a swine stimulation example. The [EBRAINS public Dataset search](https://search.kg.ebrains.eu/api/groups/public/search?q=ECAP&type=Dataset&from=0&size=40) returned zero for exact ECAP. These metadata searches do not exclude unindexed files. NIH/NINDS inventory routes were blocked; the [ODC-SCI data-use terms](https://odc-sci.org/about/odc-data-use) distinguish CC BY published data requiring login from unpublished access. No specific qualifying dataset was identified, so `RES-04/05` and `STOP-H3-A` remain open.

PA-04 gained two primary-verified citation dispositions: `S765` references [Parker et al. 2013](https://pubmed.ncbi.nlm.nih.gov/23844589/) at reference 19, an ECAP study in ten anesthetized sheep; [Falowski et al. 2025](https://www.ebi.ac.uk/europepmc/webservices/rest/PMC11760812/fullTextXML) cites `S765`, `S767` and `S798` and studies a late epidural-recording component against EMG timing in two people. Neither validates ECAP-based pain prediction. Additional worker-discovered citation leads remain unpromoted pending direct primary review; PA-04 saturation is false.

For EVD-03, the [S804 author poster](https://www.medtronic.com/content/dam/medtronic-wide/public/united-states/education-training-research/clinical-evidence/scs-patient-selection-poster-nans.pdf) was re-read visually. Evidence-matrix row 158 now includes its 80/20 split, repeated five-fold CV and Table 2 metrics. The poster conflicts internally for its combined back/leg subgroup: prose says 274/363 responders; Table 1 says 267 responders and 96 non-responders. The conflict is retained without choosing a corrected number. Random-forest specificity is 0.246, and no ECAP predictor or independent external validation is reported. For SRC-04, a cached S282 v1 PDF was independently re-extracted and its References pp. 32-41 contain no S794/S795 citation; the S212 relation and historical 27-lead list remain unresolved. The cached PDF SHA-256 was `1cf01ae13046f55174078c5d19b737e065f4ffb4fb45557bffb6d15997f52fd3`; a different worker-reported PDF hash was not reproduced and was not used. S740 exact matrix lineage and S088 full IEEE method remain unavailable.

At this slice `scripts/check.ps1` passed: 237 sources, zero validation errors/warnings, Ruff clean, pytest **70 passed** with one Starlette dependency deprecation warning. `researchctl novelty-check` retains `STOP-UNSATURATED`/`G0_REVISE`; MCP tests passed **5/5**; `git diff --check` passed. Independent SHA-256 recomputation matched all **49** release-manifest entries and aggregate `b47573846876f5fb1fad36c83a564b93019dd76b81ace21ca0b35ede18b847d4`; TODO remains **17/43** scientifically closed.

## Bibliography and prior-art reconciliation, 27 September 2026

The accessible [S212 version-2 JATS bibliography](https://www.ebi.ac.uk/europepmc/webservices/rest/PPR1092389/fullTextXML) has 78 uniquely identified references and cites neither `S794` nor `S795`; R51/Polizos is a positive extraction control. This resolves the stated relation only for that version. The historical 27-lead list and later preprint versions remain unreconciled, so `SRC-04` stays open.

The PA-04 audit adds three directly checked routes: [Cedeño et al.](https://www.ebi.ac.uk/europepmc/webservices/rest/PMC12256503/fullTextXML) cite `S786` at B39 in an animal electrode-impedance context; the [Saluda patent](https://patents.google.com/patent/US9872990B2/en) and its [related WO record](https://patents.google.com/patent/WO2015168735A1/en) list `S771` as earlier artifact prior art; and [the human evoked-EMG study](https://pmc.ncbi.nlm.nih.gov/articles/PMC11624988/) cites `S767` at reference 31. The EMG study reports 18 participants and nine with at least 50% NRS reduction at three months, whereas [NCT05459324](https://clinicaltrials.gov/api/v2/studies/NCT05459324) reports actual enrollment 10, no posted results, and no IPD-sharing module. The discrepancy remains unresolved. None of these routes establishes a linked human ECAP-to-pain dataset or completes citation saturation.

The `S804` author-poster Table 2 metrics already present in the evidence matrix are now also in the NS-11 prediction audit, eliminating the earlier statement that they were not transcribed. They remain poster-reported test metrics with unverified split implementation and no established external validation. `PA-05` stays open.

The [NCT07413731](https://clinicaltrials.gov/api/v2/studies/NCT07413731) and [NCT07502612](https://clinicaltrials.gov/api/v2/studies/NCT07502612) registrations were compared field by field. They share Brai²n/ZAS Augustinus, investigator and contact, and overlapping PSPS-T2/Evoke medication-tapering eligibility, but have separate organization study IDs and estimated enrollments of 50 and 20. Neither registration identifies participant overlap or independence. The NS-14 audit records this unresolved cohort relation, so the two registrations are not counted as independent clinical evidence.

After this integration, `scripts/check.ps1` passed with **237 sources**, zero validation errors/warnings, Ruff clean and **70 passed** tests; the dedicated MCP suite passed **5/5**. `researchctl novelty-check` remains `STOP-UNSATURATED`/`G0_REVISE`. The release manifest has **49** entries, TODO **17/43**, and aggregate SHA-256 `7d99f77bdfb29acfa03fb48f86cd964702b434f5efb34479d223e957f5fc343d`.

## Further EVD, registry and data-access checks, 27 September 2026

The [S800 publisher full text](https://link.springer.com/article/10.1186/s42234-023-00106-5) shows ten acute swine overall, but five in the referencing statistics and four in the lead-shift analysis. Recordings after euthanasia were used to separate neural signal from artifact; lateral shifts had variable ECAP-magnitude effects without a significant latency difference. Evidence-matrix row 156 now gives these denominators and directional limits.

The [S105 IOP Version of Record](https://iopscience.iop.org/article/10.1088/1741-2552/adbfbe/pdf) was independently read through a text rendering of the official URL because direct IOP GET returned a Radware CAPTCHA. Section 2.2 reports 15 recruited participants, 30 selected sessions from eight, and two later-excluded sessions. Section 2.7 uses every eleventh waveform in each outer cross-validation fold, with no participant-held-out split reported; Table 1 gives AUC median d-prime 2.44 for ECAP/non-ECAP discrimination. Row 20 now records those facts and the request-only, ethics-restricted data statement. The three EVD Picodex tasks yielded one settled primary-verified result; two stalled tasks were cancelled without integration.

The [PMC12015077 pooled dose-response article](https://www.ebi.ac.uk/europepmc/webservices/rest/PMC12015077/fullTextXML) and its [public supplement archive](https://www.ebi.ac.uk/europepmc/webservices/rest/PMC12015077/supplementaryFiles) were independently inspected. The archive contains two DOCX method/figure files and eight figure images, while the article offers data on reasonable request. Supplementary methods define one maximum-analgesic-effect visit per patient with preceding-week physiology, but no reusable patient-level linked export or license is published in those files. A [Neuron physiological near-match](https://doi.org/10.1016/j.neuron.2023.10.021) reports one person's acute ECAP/paresthesia comparison at 150 Hz versus 1 kHz; the accessible publisher supplement has no longitudinal pain-outcome dataset. The direct publisher full text was blocked and only its publisher-indexed first Results paragraph was used. `RES-04/05` stay open.

The two Brai²n registrations share site, investigator, contact and overlapping eligibility, but no registry field proves participant overlap or independence. Their cohort relation is now explicit in the NS-14 registry audit. `PA-06` stays open.

One RES Pi task settled with `agent_settled` and zero exit; its other task was cancelled after stalling. Automatic approval review rejected scratch cleanup with reason `blocked by policy`, so ignored files remain at `research/.work/pi-workers/ea019551-e852-4f20-bdb9-decf7174a0a0/res04-author-deposits-2/raw/`. The NS-11 reviewer independently confirmed that the S033 full paper cannot supply missing S046 methods: the described cohort and EEG acquisition differ. Its attempted cleanup was likewise rejected; `research/.work/supplementary-scrape.xml` remains ignored. No rejected deletion was retried through another route, and no raw worker artifact entered canonical `data/`.

After this batch, `scripts/check.ps1` again passed with **237 sources**, zero validation errors/warnings, Ruff clean and **70 passed** tests; dedicated MCP tests passed **5/5**. `researchctl novelty-check` still reports `STOP-UNSATURATED`/`G0_REVISE`. The later same-day NS-09 lead was added to the PA-04 queue without claiming citation saturation; after that audit/TODO edit, the manifest has **49** files, TODO **17/43**, and aggregate SHA-256 `ad6064e734dbefa00e0174b3c32d9eef95397e793a5a7fc70beb4af87d71d068`.

## Focused source-card and evidence-matrix reconciliation, 27 September 2026

The S105 IOP Version of Record findings already recorded in evidence-matrix row 20 were reconciled into the canonical source card through applied review batch `data/curation/relevance-5/batches/r5-correction-s105-vor-2026-09-27.json`. Its participant/session counts, every-eleventh-waveform split, request-only data access and absence of a linked clinical outcome now agree across the card, field resolutions and matrix. `review-check` and `review-apply --apply` passed after correcting the batch's field-resolution consistency; the failed first apply rolled back without changing the card.

Independent review of [S092's eLife Version of Record](https://elifesciences.org/articles/95379) clarified evidence-matrix row 97: epidermal calcium responses to stretch/poke, sensory-neuron responses and larval behaviors were tested in distinct paradigms. Epidermal Stim/Orai knockdown attenuated sensitization to the second mechanical stimulus without changing the first-stimulus response (Fig. 6A–B). The matrix now states those boundaries and does not infer subjective pain or human transfer. The S071 Essex thesis locator was repaired from damaged section markers to explicit chapter/section names; its participant-held-out results were independently confirmed. Focused checks of S029, S030, S154, S229 and S747 found no claim-changing contradiction in their accessible primary texts. Timed-out Pi tasks were cancelled and their partial responses were not used as evidence.

`scripts/check.ps1` passes for this evidence slice: `researchctl validate` reports 237 sources, zero errors/warnings and zero unresolved fields; Ruff passes; pytest reports **70 passed** with one dependency deprecation warning. The scientific TODO remains **17/43** and the gate remains `G0_REVISE`.

The [author-hosted complete Sagalajev journal PDF](https://prescottlab.ca/images/pdf/2023Sagalajev.pdf) resolves the earlier direct-publisher access limitation. Its Results/Fig. 1A and STAR Methods show one chronic-pain SCS-trial participant, 150 Hz versus 1 kHz at the same 9.6 mA setting, with an ECAP and paresthesia only at 150 Hz. Electrophysiology data are offered on reasonable request; the public modeling code is not a linked pain-outcome dataset. [Rogers et al. 2024](https://pmc.ncbi.nlm.nih.gov/articles/PMC11211721/) directly cites the paper. The RES and PA-04 audits and TODO now cite the full-text route, while complete citation coverage and a separate source card remain pending. No clinical outcome or saturation claim follows from this correction.

Final gates for this slice: `scripts/check.ps1` passed again (237 sources, zero validation errors/warnings, Ruff clean, 70 pytest passed); MCP tests passed **5/5**; `researchctl novelty-check` retained `STOP-UNSATURATED` and `G0_REVISE`; `git diff --check` passed. The refreshed 49-file release manifest records TODO **17/43** and aggregate SHA-256 `50153d3061d0dc5522e34fb14125150be36283f89d1ec7e262a178fd5b662b08`.

## Figure 2 input lineage, S830 and focused matrix review, 27 September 2026

The [official Zenodo simulation record](https://zenodo.org/records/22260924) identifies four Figure 2 runs. Archived configurations were extracted from the four official ZIP members and checked independently against their SHA-256 hashes and `experiment.wPath`: MANC `28123286`, FANC `rerun_20260324_01`, mCNS `33241780` and BANC `33241778`. `data/drosophila-connectome-audit.json` now records the exact member, processed matrix, panel and extracted-config hash for each. None specifies the upstream neuPrint/CAVE release, materialization, export query or source matrix checksum. `SRC-03` remains open and `upstream_release` remains `not_reported` for all four.

The author-hosted Sagalajev PDF was visually checked where text extraction had rendered `50 μs/phase` as `50 ms/phase`; the canonical access audit and new card use the printed microsecond unit. Card `S830` was staged, passed a dry publication with zero warnings, and was applied through `researchctl publish`; its DOI and PMID did not collide with the existing roster. The automatic rollback snapshot is under ignored `.work/research-snapshots/2026-09-27T181941Z-pre-publish`. This one-person ECAP/paresthesia result is physiological prior art, not a pain-treatment outcome, and PA-04 citation saturation is still open.

Four matrix rows received an individual primary-text review. `S360` now exposes 15 successful day-0 trials, 13 implants and 11 follow-ups; the clinical and ECAP summaries remain separate. `S008` distinguishes 51 people in its cited source cohort from 50 analyzed in the later paper and distinguishes pooled confusion counts from reported mean accuracy. `S015` now calls its 15-person same-protocol phase a GUI evaluation; the paper labels Figure 4 a GUI simulation phase and does not give an evaluation-window denominator. `S236` retained its bounded existing row. No clinical transfer or causal SHAP inference was added. The EVD audit records the checked primary sections; `EVD-03` remains open.

For NS-15, official RSL viewer APIs were independently rechecked: Isagulyan dissertation `rsl01004299840` returns `restricted`, 278 pages and no download; Blagorazumova `rsl01000275094` returns 404 while a neighbouring free abstract resolves on the same API. These are document-specific access limits, not method reviews or negative analogue results. Two overlong NS-05 Pi searches were cancelled after about 15 minutes without `agent_settled`; their incomplete output was excluded and status stubs were stored in their assigned ignored `.work/pi-workers/515d0962-0cbf-466b-9643-eec682e464d7/` folders. Other settled NS-05 leads remain unintegrated until primary review.

This slice passes `scripts/check.ps1` (238 source cards, zero validation errors/warnings, Ruff clean, **70 pytest passed**), `researchctl novelty-check` (`STOP-UNSATURATED`, `G0_REVISE`), focused MCP tests (**5/5**) and `git diff --check`. Independent SHA-256 recomputation matched all **49** release-manifest file hashes and aggregate `0fd48d83b218d57932eb1cb35256301c3fe0f06a2ddb0095ad9bd18950478b44`. TODO remains **17/43**; the remaining 26 scientific criteria have not been converted to operational STOP checkboxes.

## Focused NS-05, PA-04, RES-04 and EVD review, 27 September 2026

The primary [Nature Communications HIPPIE article](https://www.nature.com/articles/s41467-026-76939-w), Results/Fig. 5, supports a macaque-to-mouse neuronal cell-type representation comparison, not Drosophila-to-human ECAP/SCS or pain transfer. Card `S831` was staged, passed publication dry-run without warnings and was applied; the publication snapshot is under ignored `.work/research-snapshots/2026-09-27T184240Z-pre-publish`. The NS-05 protocol and TODO now reference its canonical ID. Its companion TN-VAE preprint requires human fine-tuning, as the prior audit already records. NS-05 citation and motif coverage remain open.

The PA-04 audit now records three independently checked forward citation edges from S830. [Ladner et al.](https://www.ebi.ac.uk/europepmc/webservices/rest/PMC13519873/fullTextXML) report rat/macaque epidural electrophysiology; a [mouse slice study](https://www.ebi.ac.uk/europepmc/webservices/rest/PMC11802663/fullTextXML) examines local temperature; and [Xu et al.](https://www.ebi.ac.uk/europepmc/webservices/rest/PMC11723817/fullTextXML) cite S830 twice in Discussion while measuring mouse NK1R-positive neural calcium responses. None supplies a human patient-level ECAP-to-pain predictor. Same-day edges are not a later saturation update, so PA-04 remains open.

The bounded public-catalog access audit records DANDI 911 public entries, PhysioNet exact topic routes, and Figshare's targeted owner records. The [Figshare near match](https://api.figshare.com/v2/articles/33092858) provides a CC BY 4.0 supplementary DOCX for an SCS care-workflow pilot, but its owner record does not document ECAP measurements or a linked ECAP/pain table. The named [NCT06229470 registry](https://clinicaltrials.gov/api/v2/studies/NCT06229470) likewise has no posted results and reports no IPD sharing. These checks do not establish a qualifying reusable human dataset; `RES-04/05` remain open. The Mendeley worker exceeded its timebox and was cancelled without `agent_settled`; no partial finding was integrated. Automatic approval review rejected cleanup of 313 ignored raw files (~47.1 MB) at `.work/pi-workers/f7751d1b-cda4-4150-806b-b1e6bb152444/mendeley-exact-records/raw/` as `blocked by policy`; the status stub and files remain, with no alternate deletion route attempted.

The [S036 RUA publisher PDF](https://rua.ua.es/server/api/core/bitstreams/ab49f761-3afc-4a6d-9e37-79a56266ab0d/content) supports the corrected evidence-matrix row 3 and an applied source-card review batch `r5-correction-s036-rua-fulltext-2026-09-27`. The first apply failed integrity checks because the draft omitted an exact-URL field resolution and used `note` rather than the review tool's `notes` key; it rolled back. The corrected batch passed with zero errors and warnings, and its permanent copy is in `data/curation/relevance-5/batches/`. Draft access-status changes for `S039` and `S082` were not applied: S039's other study-result fields still need a coherent primary review, and S082's indexed abstract/conclusion numbers remain unresolved. `EVD-03` stays open. Scientific TODO progress is **17/43** and the gate remains `G0_REVISE`.

Checks for this slice: `scripts/check.ps1` passed with **239** sources, zero validation errors/warnings, Ruff clean and **70 pytest passed** (one Starlette dependency deprecation warning); MCP tests passed **5/5**. `researchctl novelty-check` remains `STOP-UNSATURATED` under `G0_REVISE`.
The 49-file release manifest was refreshed and independently verified entry by entry; its aggregate SHA-256 is `ce958bb09f2a04358cef16bd39279d7e87d646cf36f9fd95b15bf8baf114994a`. `git diff --check` passed.

## Bounded source follow-up, 27 September 2026

The S046 publisher conference abstract was reconciled into its source card and evidence-matrix row through reviewed batch `r5-correction-s046-abstract-status-2026-09-27`. The abstract supports a 16-person preoperative-EEG study and author-reported performance, but the full method and participant split remain unavailable. The official S282 bioRxiv v1 JATS contains 95 numbered references, correcting the previous 123-reference claim; the identity-level screen does not prove complete nociception citation coverage. Neither correction closes PA-05 or SRC-04.

An individually dated S088 IEEE owner REST response supplied its abstract, five figure captions and 20 references. S245's official CNIPA signed query supplied its A/B publication records and abstract. The S088 full article and S245 claims remain inaccessible on the checked routes; the SRC-07 ledger and version audit record these bounded findings, without treating this five-source follow-up as a fresh all-81 snapshot. S754 and S763 checks found no new version relationship in the examined primary routes. Eight S740 lineage tasks yielded four settled results and four cancelled searches; no exact upstream release link for the four processed matrices was established.

The proposed S039/S082 publisher-access review batch was withheld from canonical application pending reconciliation of access routes. S039's saved first-page route is an HTML access challenge and its anonymous Elsevier API response is coredata only; however, the [publisher-indexed Abstract](https://www.sciencedirect.com/science/article/abs/pii/S174680942601815X) itself reports the six-class result and four subject-wise folds. Its separately indexed Dataset source and details excerpt describes 52 PMED participants, without establishing the analyzed model denominator. S082's [publisher first-page PDF](https://www.sciencedirect.com/sdfe/pdf/download/eid/1-s2.0-S1746809426003691/first-page-pdf) supports 93.98% in the Abstract; the [publisher-indexed Conclusions](https://www.sciencedirect.com/science/article/pii/S1746809426003691) separately state 91.79%. Their protocols and denominators have not been reconciled. The card update will distinguish indexed excerpts, directly retrieved first-page text and unavailable full methods.

Automatic approval review rejected removal of the 46-byte untracked reserved-name artifact `R:\Aspa\nul` with `blocked by policy`; it remains outside the research subproject. It also rejected cleanup of raw files from the cancelled S763 Pi task under the ignored `.work/pi-workers/a3fd5d06-8227-4080-9b22-ad7068dc5e14/src08-s763-biorxiv-journal-refresh/raw/` directory. Neither path was deleted by another route.

After these integrations, `scripts/check.ps1` passed with 239 source cards, zero validation errors/warnings, Ruff clean and 70 pytest passes; focused MCP tests passed 5/5. `researchctl novelty-check` retained `STOP-UNSATURATED` and `G0_REVISE`; `git diff --check` passed. The 49-file release manifest was refreshed and independently recomputed: aggregate SHA-256 `ee6d1e7a3daabf40450c52cf8e2dceb0f07d72e23ab98a019c0766329e3f0f2a`, TODO 17/43.

The S039/S082 follow-up was subsequently applied as reviewed batch `r5-correction-s039-s082-publisher-access-2026-09-27`. An initial apply rolled back because four field resolutions did not match their updated values; the corrected batch passed `review-check` and `review-apply --apply` with zero errors and warnings. S039 is now `partially_verified` at publisher-indexed excerpt level, with `sample_size` unresolved rather than equated to PMED's 52 distributed participants. S082 is `partially_verified` at publisher first-page and indexed-Conclusions level, retaining the unexplained 93.98%/91.79% distinction. Neither card claims a checked full article or external clinical validity. Matrix rows 2 and 9 and the EVD-03 review log now carry the same boundaries; the scientific TODO remains open.

Post-application gates passed: `scripts/check.ps1` validated 239 source cards with zero errors/warnings, Ruff clean and 70 pytest passes (one dependency deprecation warning); MCP tests passed 5/5; `researchctl novelty-check` retained `STOP-UNSATURATED` and `G0_REVISE`; `git diff --check` passed. The test expectation for the `verified_primary` PainMonit search was updated to exclude the now `partially_verified` S039 card. The refreshed 49-file manifest was independently rehashed entry by entry, aggregate SHA-256 `285888ce28f3264201cd7b2b6553e2cff584e5a934deedc7b2dc84a67ab47ea6`, TODO **17/43**.

## Version drift and S282 bibliography, 27 September 2026

The dated S212 owner recheck found a positive bioRxiv v3 title/content update, while Europe PMC still serves JATS v2. The reviewed batch `r5-correction-s212-v3-title-version-2026-09-27` updates the canonical title and version-specific note, keeping detailed earlier measurements tied to the v2 primary locators. Because a new all-81 source refresh has not followed, `SRC-08` was reopened. The scientific TODO is **16/43**, gate `G0_REVISE`.

The S282 v1 official JATS contains 95 references. Two additional source cards were published after independent primary-text review: `S833` ([Poe et al., eLife 53351](https://elifesciences.org/articles/53351)) separates heat-probe rolling from dendrite morphology; `S834` ([Rosenzweig et al., Genes & Development](https://pmc.ncbi.nlm.nih.gov/articles/PMC548941/)) records a genotype- and assay-specific negative withdrawal comparison around 55 °C. Neither paper records stimulus-evoked neural activity in those experiments. The NS-03 audit and search protocol now contain 42 canonical candidate IDs with separate stimulus, neural, behavior and pain boundaries. The historical aggregate of 27 unnamed leads is still unreconstructable; `SRC-04` remains open.

For this integrated slice, `scripts/check.ps1` passed with **242** sources, no integrity warnings, Ruff clean and **70 pytest passes** (one dependency deprecation warning). `researchctl novelty-check` retained `STOP-UNSATURATED`. The 49-file manifest was independently checked entry by entry: aggregate SHA-256 `0c41ad2c7dd7b22987824ae1f6ce31f9ca2de54d1e0054a7d352bd2c442b77be`, TODO **16/43**. The EVD-03 worker follow-up is still in progress and is outside this integrated slice.

## Current source slice, 28 September 2026

The distinct Yoshino et al. bioRxiv v1 heat-off preprint was published as `S835` after primary PMC/byline and exact DOI review. Its epidermal GCaMP6s signal and separate larval rolling assay are recorded independently in the NS-03 audit; no direct stimulus-evoked neural recording or human pain/ECAP/SCS measure is claimed. Figure 1 caption states 30 seconds after Peltier heat, while Methods states 10 seconds; the discrepancy remains unresolved. The NS-03 audit now has **43** four-field source extractions. `SRC-04` remains open for historical bibliography/citation coverage and `SRC-03` lineage.

After this integration, `scripts/check.ps1` passed: **243** sources, no integrity errors or warnings, Ruff clean, **70 pytest passes** and one dependency deprecation warning. `git diff --check` passed. The 49-file release manifest was independently rehashed entry by entry, with aggregate SHA-256 `ef41b376fa3848aadc8aac9c53c6e76396d8a7771c041ba60ab833b3c3a7b264`; the scientific TODO remains **16/43** and `G0_REVISE`. The unfinished 81-ID refresh and PA-06 cohort proposals are outside this integrated slice.

## Prior-art and version-delta slice, 28 September 2026

The 81-ID `SRC-08` refresh is now complete at the Pi receipt level (10/10 settled with zero exit), but its detected content deltas are not all resolved. Reviewed corrections updated S782's author byline and S763's owner v2 self-correction. S330's v2 title/version metadata is distinguished from the inaccessible scientific body. A later bounded comparison of the [Google Research owner post](https://blog.google/innovation-and-ai/technology/research/male-fruit-fly-brain-map/) with a 16 September archive shows only an update note and Cambridge team credit in the first paragraph among the compared article sections. The exact claimed 21 September edit time is owner metadata. S097, S212, S231 and S738 retain unresolved content or access questions; incomplete or receipt-less Pi outputs were excluded. `SRC-08` remains open.

The primary [JPHV S357 PDF](https://jphv.ub.ac.id/index.php/jphv/article/download/306/93), fetched by a settled worker and independently checked from the saved PDF by root, conflicts internally over RR versus RD 0.18 for the >=80% threshold and misstates the 36-month EVOKE open-loop >=50% rate. The [primary EVOKE report](https://pmc.ncbi.nlm.nih.gov/articles/PMC11103285/) gives 49.3% for >=50%; 31.3% belongs to >=80%. The source card, matrix row and EVD audit now bar independent-effect and three-independent-trial claims. `EVD-03` remains open.

Two new NS-06 prior-art cards were staged and published from primary sources: S836, [Choi et al.](https://www.nature.com/articles/s41746-026-02778-0), is synthetic EEG augmentation for chronic-pain case/control classification with participant-disjoint internal validation; S837, [Rathee et al.](https://link.springer.com/article/10.1007/s10044-021-01025-4), is abstract-level labeled few-shot facial-pain subject adaptation. They are partial analogues with different labels and transfer protocols from S149. Their discovery resets the consecutive clean PA-03 refresh count to zero; the earliest distinct next date is 29 September. S088 full methods and complete citation coverage remain unresolved. `PA-03` remains open.

For PA-04, root independently re-queried Crossref and Europe PMC for S764 and found zero citing works in those two indexes only. Root fetched the primary [Mirzakhalili et al. JATS](https://www.ebi.ac.uk/europepmc/webservices/rest/PMC10535048/fullTextXML) and verified reference `jneacf522bib31` plus its in-text model-reuse xref to S766. The official [NCBI BioC XML for Khadka et al.](https://www.ncbi.nlm.nih.gov/research/bionlp/RESTful/pmcoa.cgi/BioC_xml/PMC13552472/unicode) independently confirmed the S766 DOI in its references and the R2 source pointer in Table 1 of the computational tissue-parameter analysis; Europe PMC JATS returned HTTP 500 for that paper. Both are computational lineage edges, not patient ECAP-to-analgesia evidence. Other Pi-discovered edges await individual primary review; two overlong Pi tasks were cancelled and excluded. `PA-04` remains open.

Current gates: `scripts/check.ps1` passed with **245** sources, zero validation errors/warnings, Ruff clean and **70 pytest passes** (one Starlette deprecation warning). Dedicated MCP tests passed **5/5**. `researchctl novelty-check` retains `STOP-UNSATURATED` and `G0_REVISE`; `git diff --check` passed. The 49-file manifest was independently rehashed entry by entry: aggregate SHA-256 `bd25257c162544134a56190ff490f92013cfc1515d2f03675400a0d9107e784e`, scientific TODO **16/43**. The 43/43 operational STOP count remains historical and is not scientific closure.

## Current bounded source and access review, 28 September 2026

Card `S838` was published from the primary Mirzakhalili et al. JATS after an exact author correction. The S766 forward-citation audit now contains eleven bounded links: ten have direct reference plus in-text contexts (one Khadka context is in an owner-linked preprint because the IOP VOR body is blocked), and Zannou's printed 19–21 range spans bibliography R20 without an individual XML xref. The owner copies corrected a worker's mistaken IJMS article number and the species label of the Lam et al. swine study. None supports patient ECAP-to-analgesia prediction. `PA-04` remains open for citation coverage and later dated saturation checks.

The [NCT06057480 official registry](https://clinicaltrials.gov/api/v2/studies/NCT06057480), results first posted 2026-09-25, reports 134 successful closed-loop program generations among 140 initiated APM uses in a 30-participant study and `IPD Sharing=NO`. This workflow measure does not provide pain/function outcomes or participant-linked ECAP records. The existing HES APM candidate and the live access audit were updated; `RES-04/05` remain open under `STOP-H3-A`. Five Pi catalog checks settled; an ICPSR task was cancelled and excluded.

The `S243` registry card's stale 2027 estimate was corrected through reviewed batch `r5-correction-s243-registry-2026-09-28`; the [current official record](https://clinicaltrials.gov/api/v2/studies/NCT04662905) estimates completion in 2029, remains recruiting and has no posted results. The linked primary paper explicitly says no baseline pain or therapy-efficacy outcomes were collected. The matrix and EVD audit preserve planned ECAP versus observed clinical outcome boundaries. Four Pi EVD checks settled; the S289 job lacked a recoverable receipt, so its saved output was excluded.

For `SRC-08`, owner v1/v2 JATS for `S212` show an added Kenyon-cell Results subsection and Figure 5C behavioral text in v2; the v2 owner note simultaneously says no new data or conclusion was added. The audit records both without inferring when the assay was performed. A bounded primary-copy comparison for `S738` records preprint v3 versus Nature VOR count and wording changes, while keeping their release contexts distinct. `S097` was cancelled before settlement; `S231` lacks the needed September HTML before/after pair. `SRC-08` remains open.

After these integrations, `scripts/check.ps1` passed: **246** sources, zero integrity errors/warnings, Ruff clean, **70 pytest passes** with one dependency deprecation warning. Dedicated MCP tests passed **5/5**; `researchctl novelty-check` retained `STOP-UNSATURATED` and `G0_REVISE`; `git diff --check` passed. All **49** release-manifest file hashes and its aggregate SHA-256 `704bae5ab155706da5e51bd0336238a579aee5a6d4a4505cff2fd7781b7b434c` matched an independent recomputation. The scientific TODO remains **16/43**; these checks do not establish scientific completion or `GO`.

## Later 28 September source version and evidence slice

The S766 forward-citation tail added Khadka's RADO-SCS model and Zander's ECAP modeling article to the bounded audit. Root also corrected the worker's treatment of Zannou: its [PMC JATS](https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi?db=pmc&id=PMC13539576&retmode=xml) prints reference range 19–21, which includes S766 at bibliography R20 even though only R19/R21 are XML xref anchors. The link is recorded as range-mediated with no source-specific attribution of the whole sentence. The complete list now has **11** bounded citation links; `PA-04` remains open.

Fresh owner JATS for `S212` shows v3 retains the Kenyon-cell behavior experiment but changes Figure 5C group counts from 450/454 to 366/351 and reports less rolling plus more turning. New Figure 6 author-reports AUC 0.74 and 72.4% strict accuracy for model-to-observed neuron-valence ranking, but the checked Results/Methods do not identify its exact evaluation N or train/test split. The [owner supplement](https://www.biorxiv.org/content/biorxiv/early/2026/08/03/2025.09.25.678485/DC1/embed/media-1.pdf?download=true) Table S5 is a two-hop lineage-count table, not validation observations. The source version audit preserves the text delta without treating these metrics as reproduced or externally validated; `SRC-08` remains open.

EVD-03 wave 3 independently checked the S784/S785 primary abstracts, the [S786 accepted manuscript](https://researchcommons.waikato.ac.nz/bitstreams/a7586cec-1b63-4d68-99db-bf0c698a6194/download), and [S788 PubMed abstract](https://pubmed.ncbi.nlm.nih.gov/28922517/). Reviewed batch `r5-correction-s786-s788-primary-boundaries-2026-09-28` records saline-bench only artifact-model comparison and exact interim AVALON response percentages separately from its ECAP device endpoint. Four Pi tasks settled successfully; an S193 task failed without `agent_settled` and its output was excluded. `EVD-03` remains open.

Current gates after this slice: `scripts/check.ps1` passed with **246** sources, zero integrity errors/warnings, Ruff clean and **70 pytest passes** (one dependency deprecation warning); dedicated MCP tests passed **5/5**. `researchctl novelty-check` retained `STOP-UNSATURATED` and `G0_REVISE`. The subsequent explicit supplement locator refresh gives release-manifest aggregate SHA-256 `2e9c9a1f70ef0f47b3a8af5d16b26983120de642f56558f7e5e0db46991715ad` across **49** files; scientific TODO **16/43**. This is a checked progress slice, not scientific completion or `GO`.

## Population-unit reconciliation, 28 September 2026

Three existing positive evidence-matrix rows now state the experimental units supported by their primary full texts: S212 distinguishes the same-specimen first-instar CNS activity/anatomy registration from separate third-instar assays; S282 distinguishes dissected wandering third-instar CNS functional tests from larval rolling; S092 distinguishes third-instar behavioral tests, dissociated or semi-intact epidermal calcium assays, and a separate semi-intact epidermis-to-sensory-neuron assay. The exact primary locators and forbidden cross-assay inferences are recorded in EVD-03 review XXIII. These refinements do not close `EVD-03`.

`researchctl validate` reported 246 sources and zero errors/warnings, `scripts/check.ps1` passed Ruff and all **70 pytest tests**, dedicated MCP tests passed **5/5**, `researchctl novelty-check` retained `STOP-UNSATURATED` and `G0_REVISE`, and `git diff --check` exited successfully. The refreshed 49-file release-manifest aggregate is `12162057f379278816c4efe4cef3fa63a7c0b1ef68512911d2e45a9e1f109783`; TODO remains **16/43**, gate `G0_REVISE`. Parallel EVD, PA-05 and S097 checks were still under review and are outside this slice.

## Targeted S097 and EVD reconciliation, 28 September 2026

The two exact owner-hosted S097 PDFs were rehashed and inspected directly. The bounded version audit now records the byline change on p. 1 and funding/IRB/consent back-matter differences on Edition A p. 46 versus Edition B p. 45. Root inspection rejected a proposed grant-identifier change: both rendered editions show `(QU-APC-2026)`. The publisher version-note body and scientific Table 1/Section 1.1 comparison remain unresolved, so `SRC-08` stays open.

EVD-03 review XXIV updated six matrix rows from S090, S190, S200, S286, S320 and S368 primary sources. It keeps S090's planned N separate from achieved data, S190 validation and test results separate, and S286's Figure 2a FAFB v783 visualization separate from the unspecified policy-graph release. Root reconciled S320's paper, README and code discrepancies and narrowed its claim to simulated mode fractions and CI proxies. Unreceipted or cancelled Pi outputs remain outside the canonical matrix. `EVD-03` stays open, as do `PA-05` and the scientific gate.

After this integration, `scripts/check.ps1` passed: 246 sources, zero validation errors or warnings, Ruff clean and **70 pytest passes** (one dependency deprecation warning). Dedicated MCP tests passed **5/5**; `researchctl novelty-check` retained `STOP-UNSATURATED` and `G0_REVISE`; `git diff --check` passed. The subsequent TODO locator update was revalidated, and the 49-file release manifest was independently rehashed entry by entry, with aggregate SHA-256 `9f5b22253b7e433ebfa4c970db3584d68c6dce0277839c6040b1b825b25d1570`. Scientific TODO remains **16/43**; the checks do not establish scientific completion or `GO`.

## Bounded S097 and clinical-data screen, 28 September 2026

A focused comparison of the two owner-hosted `S097` PDFs found no wording difference in Section 1.1 after normalizing line breaks. Table 1 reference [32] has a blank Year cell in Edition A printed p. 3 and `2024` in Edition B printed p. 4; root checked the extracted row against the rendered pages. The all-cell Pi task timed out and was cancelled, so this does not establish that the table has no other changes. The exact URLs, edition hashes, locators and limits are in `data/src07-version-recheck-audit.json`. `SRC-08` remains open.

The targeted `RES-04/05` review independently re-fetched seven exact [ClinicalTrials.gov v2 records](https://clinicaltrials.gov/api/v2/studies/NCT05177354) and screened their declared IPD sharing and result availability. NCT05177354 has only aggregate posted results and declares IPD sharing `NO`; NCT07209514 is undecided and has no results; five further records declare `NO` and have no posted results. The compact IDs and scope are in `data/human-ecap-scs-access-audit.json`. No checked route supplied reusable participant-level ECAP and pain/function linkage. This is a bounded negative screen, not proof that no qualifying dataset exists anywhere; `RES-04/05` and `STOP-H3-A` remain open.

The current `NS-03` living audit metadata was reconciled with its existing 43 candidate entries and published `S835` lead; this corrects an obsolete 38-candidate operational description but adds no new scientific evidence or closed TODO item. The scientific count is still **16/43** and the gate is `G0_REVISE`.

After this slice, `scripts/check.ps1` passed: 246 source records, zero validation errors/warnings, Ruff clean and **70 pytest passes** (one dependency deprecation warning). `researchctl novelty-check` retained `STOP-UNSATURATED` and `G0_REVISE`; `git diff --check` passed. An independent rehash matched all 49 release-manifest entries and aggregate SHA-256 `935d2e086cf938d0be03091f089e4b3cfa8d6d6f58a8124519297e24d50bc51c`; TODO remains **16/43**. These gates check integrity and packaging, not scientific completion.

## EVD-03 focused repository correction, 28 September 2026

The accepted Picodex S086 lead was checked independently against the pinned HCAT-Pain README and `scripts/utils.py`. The matrix now records the README's obsolete or contradictory code-availability statement and the script's disabled subject split, without assigning that script to the published metrics. The other five targeted rows produced no integrated scientific upgrade: S039's task DOI was wrong, S785's comparator inference was rejected, S237 needs a separate article/supplement reconciliation, and S082/S790 lacked accepted receipts. The semantic review of all positive rows is incomplete; `EVD-03` stays open.

The final integrated data state passed `scripts/check.ps1` with 246 records, zero validation errors/warnings, Ruff clean and 70 pytest passes (one dependency deprecation warning); `git diff --check` passed. All 49 release-manifest hashes and aggregate `30c5dcda139faef18ca300fe028fc9d916b80ec1bb3a4d437f3f8dd2db35ed46` matched an independent recomputation. `researchctl novelty-check` remained `STOP-UNSATURATED`; scientific TODO **16/43**, gate `G0_REVISE`.

## Current SRC-04 and IPR-alignment slice, 28 September 2026

The primary [S835 JATS](https://www.ebi.ac.uk/europepmc/webservices/rest/PMC12157477/fullTextXML), reference R6, led to Turner et al. 2016 (DOI `10.1016/j.cub.2016.09.038`, PMID `27818173`). Its [author-hosted full text](https://himmellab.org/docs/Turner_Armengol_et_al_2016.pdf), Results/Figures 1, 2 and 4, separately supports cold stimulus, class III GCaMP6 calcium responses and larval contraction. The source was published as `S839` after root discovered that an earlier reported dry-run had covered only the empty template. The filled card initially failed the uncertainty vocabulary, was corrected, staged and published with zero errors/warnings. The NS-03 audit and search stream now contain 44 four-field extractions. Historical citation coverage and S740 upstream lineage remain unresolved; `SRC-04` is open.

The existing 2026–2030 IPR transfer text at `../../docs/material/IPR_chistovoi-tekst_2026-2030.md` was reconciled to the current Drosophila → separate physical ECAP → SCS concept while retaining its administrative format. It remains a proposal awaiting author and supervisor review and does not count as an experiment, human-data permission, novelty decision or `GO`.

After this slice, `scripts/check.ps1` passed with **247** sources, zero integrity errors/warnings, Ruff clean and **70 pytest passes** (one dependency deprecation warning). `researchctl novelty-check` retained `STOP-UNSATURATED` and `G0_REVISE`; `git diff --check` passed. The 49-file release manifest was independently rehashed entry by entry and matched aggregate SHA-256 `4743f887cd9cf8d393f934ca4df3f910dde345a3463dc87f8f8a7f5bb730acc8`; scientific TODO **16/43**. These checks verify the current data slice, not scientific completion.

## Current S097 claim-boundary slice, 28 September 2026

The sole S097 matrix claim is a contextual taxonomy of edge federated-learning security, with no pain, ECAP, SCS or clinical inference. Root checked its stated Sections 1.2, 3–5 and 9 in the owner-hosted Edition B/v2 full text and recorded a dated terminal disposition for this claim in `data/src07-version-recheck-audit.json`. The full A-to-B editorial comparison and publisher Versions Notes remain unresolved; no whole-paper invariance or formal correction classification is asserted. Other `SRC-08` content deltas remain open.

`scripts/check.ps1` passed again with **247** sources, zero integrity errors/warnings, Ruff clean and **70 pytest passes** (one dependency deprecation warning); `git diff --check` passed. The 49-file manifest was independently rehashed and matched aggregate SHA-256 `88adcaaaf6257450ae1460ee243a395dcade85d69c3f22a91b30738bb3996415`; scientific TODO **16/43**, gate `G0_REVISE`.

## Current S212/S231 version-claim reconciliation, 28 September 2026

Root checked the saved [owner bioRxiv v3 full text for S212](https://www.biorxiv.org/content/10.1101/2025.09.25.678485v3.full.pdf), including the Methods, neural-mapping Results/Figure 2 and Kenyon-cell Results/Figure 5C. The card's performance summary and sole matrix row now point to v3. Neural mapping (119 of about 3,000 neurons; 25 lineages; 101/119 traced) and separate third-instar behavior remain distinct. The v3 behavioral report has rolling `P=0.0037`, turning `P=0.025`, and experimental/control `n=366/351`; the v2 Figure 5C had `n=450/454`. The reason for that denominator change and Figure 6's exact evaluation unit/split remain unresolved; no human validation is inferred.

For S231, root checked the [current owner PDF v2](https://mdpi-res.com/d_attachment/sensors/sensors-26-03049/article_deploy/sensors-26-03049-v2.pdf) against the sole contextual matrix claim: Abstract/Figure 1 identify four neuromorphic domains and §§7.3/8.5 describe fragmented translation evidence. `data/src07-version-recheck-audit.json` records a dated claim-limited disposition. The purported September HTML event could not be re-confirmed or compared because live owner HTML was blocked and no later capture was found; no whole-paper invariance is claimed. The separate 81-source audit confirmed that a new canonical all-record cutoff is still missing, so `SRC-08` remains open.

After integration, `scripts/check.ps1` passed with **247** sources, zero integrity errors/warnings, Ruff clean and **70 pytest passes** (one dependency deprecation warning). `researchctl novelty-check` still reports `STOP-UNSATURATED` and `G0_REVISE`; scientific TODO remains **16/43**. The 49-file manifest SHA-256 is `7f30e2edcbc892e848231c185fd96fa39531b6c503ecf2c92cf04081547edb95`; each entry was independently rechecked against the current files.
## SRC-08 all-81 bounded refresh, 28 September 2026

Nine non-overlapping Pi results were reconciled against the 81 unique IDs in `data/src07-coverage-ledger-2026-09-25.json`. Their dated partition membership and result SHA-256 values are now in `data/src07-version-recheck-audit.json#full_81_refresh_2026_09_28`; the detailed worker files remain under ignored `research/.work`, outside the canonical data snapshot. No newly confirmed publication correction, retraction, version or linked-publication event surfaced on the accessible routes in this pass. The accessible IEEE owner PDF for `S045` was separately checked and its participant-level method and matrix claim updated; dated claim dispositions for `S149`, `S249` and other exceptions remain in the same audit.

This does not establish a zero unresolved update queue. The 25-to-26 September Frontiers `dateModified` transitions for `S149` and `S249` lack authenticated pre-transition bodies; the 3 September MDPI HTML update for `S231` remains inaccessible. Their causes and exact text deltas are unknown, although the currently included bounded claims were rechecked against accessible owner versions. `SRC-08` stays open, as do its dependent scientific TODO items; progress is **16/43**, gate `G0_REVISE`.

After integration, `scripts/check.ps1` passed (`researchctl validate`: **247** sources, zero errors and warnings; Ruff clean; **70** pytest passes with one dependency deprecation warning). `researchctl novelty-check` retained `STOP-UNSATURATED` and `G0_REVISE`; `git diff --check` passed with only Git line-ending notices. An independent SHA-256 recomputation matched all **49** release-manifest entries; manifest SHA-256 is `1debc3ccecd0702955c24231a26356664a796fbe86a562265033795c58c8890b`. These software checks do not establish a scientific `GO` or resolve the three HTML deltas.

The same dated evidence set also supersedes an obsolete access item in the version audit: `S357`'s eight-page publisher PDF (DOI `10.21776/ub.jphv.2026.007.01.07`, SHA-256 `0ba078c5470adcbd652dcc3742bf21dc09d75e79f8241ea12b2a066c4185261e`) is now accessible and its contradictory effect statements have already been bounded in the evidence-matrix review. The earlier 403 observation is retained as history; the active full-text follow-up list now names only `S034` and `S754`.

After this audit correction, `researchctl validate` passed with 247 sources and zero errors/warnings; `git diff --check` passed. All 49 release-manifest entries matched an independent SHA-256 recomputation; the current manifest SHA-256 is `4aa0f3a5bc0563c2036babf33800b07c44403712d1a3fb6125a0f072ffaa4277`. Scientific TODO and gate remain **16/43** and `G0_REVISE`.

## EVD-03 bounded matrix-locator integration, 28 September 2026

Three concurrent Codex reviews structurally screened all 162 positive matrix rows. Only 21 rows were freshly checked against primary texts in this pass (4, 11 and 6 by range); the other 141 do not acquire a new semantic verification. `S148`, `S005` and `S070` locator errors were repaired, as were `S240`, `S012`, `S066`, `S227` and `S017` in the preceding integration. Failed or cancelled Pi tasks lacked `agent_settled`; no partial claims entered the canonical matrix. The dated details and source URLs are in `data/evd03-evidence-matrix-audit-2026-09-25.md` reviews XXVII–XXVIII. `EVD-03` and `SRC-08` remain open.

After this integration, `scripts/check.ps1` passed with 247 sources, zero validation errors/warnings, Ruff clean and 70 pytest passes (one dependency deprecation warning). `researchctl novelty-check` retained `STOP-UNSATURATED` and `G0_REVISE`; `git diff --check` passed with only Git line-ending notices. A separate PowerShell SHA-256 comparison found zero mismatches across all 49 release-manifest entries. Manifest SHA-256: `3c8aadeb83d397be3ae48a8ea9292bd9f18d446f63bd2bb6d2c5e2719db3b427`. Scientific TODO remains **16/43**. These checks prove integrity of this slice, not complete scientific review.

## EVD-03 focused rows 0–20 and primary-route recovery, 28 September 2026

Three small read-only Codex reviews disposed matrix rows 0–20. Root independently confirmed and integrated narrow corrections for S078, S082, S162, S356, S105 and contextual S243, plus direct S003/S033/S289 checks. The S036 author PDF transiently returned 404 to one reviewer but was recovered with HTTP 200, the recorded SHA-256 and its Table 2 values; its full-text access remains valid. S149's conflicting neonatal validation/training wording and 120-versus-300 figure denominators remain explicit. S039 and the current IEEE routes for S088/S007 remain access-limited; their prior abstract support was not promoted to full-method verification. Details and primary URLs are in `data/evd03-evidence-matrix-audit-2026-09-25.md` reviews XXIX–XXXI. `EVD-03` and `SRC-08` remain open.

After integration, `scripts/check.ps1` passed with **247** sources, zero validation errors/warnings, Ruff clean and **70** pytest passes (one dependency deprecation warning). `researchctl novelty-check` returned `STOP-UNSATURATED` and `G0_REVISE`; `git diff --check` passed with only Git line-ending notices. Independent PowerShell SHA-256 comparison matched all **49** manifest entries, manifest SHA-256 `0b949be805684316efd05ddc1eae762c0fab92d21e72012b9a4a4a92758fca56`. Scientific TODO remains **16/43**. These checks do not prove scientific completion or clinical validity.
## EVD-03 focused review, rows 21–42 (28.09.2026)

Two bounded reviewer passes covered matrix indices 21–30 and 31–41; the root agent independently checked the changed primary routes and reviewed row 42. The official NCT04765735 API reports 52 actual enrollees but 42 in the participant-flow totals, matching the published ECHO-MAC ITT n=42; the unexplained difference is now explicit in `S239`. `S289` no longer claims a patent-claim review from cover metadata. The Aalborg institutional record identifies `S164` as a systematic review with narrative synthesis of 35 studies, and its locator now names the record rather than calling it the linked PDF. `S284` points to the accessible publisher-deposited JATS and exact sections. Details and access limits are in `data/evd03-evidence-matrix-audit-2026-09-25.md`, reviews XXXII–XXXIV. This does not finish all 162 positive rows or the `SRC-08` prerequisite.

`scripts/check.ps1` passed: 247 sources, zero validation errors/warnings, Ruff clean, and 70 pytest passes with one dependency deprecation warning. `researchctl novelty-check` remains `STOP-UNSATURATED` and `G0_REVISE`; `git diff --check` found no whitespace errors. An independent SHA-256 check matched all 49 manifest entries and the aggregate digest; the current manifest SHA-256 is `a3fde42afee81d85d5ba9007479873181b04fa6e5be355d807f786359063ce60`. Scientific TODO remains 16/43. The older `.work/verify_current.py` is stale because it hardcodes a historical source-distribution count, so it was not used as the integrity gate.
## EVD-03 focused review, rows 43–81 (28.09.2026)

Two read-only Codex reviewers audited rows 43–55 and 56–68, and root checked selected rows 69–81 against available primary full texts and abstracts. The matrix now points `S190` to version-specific arXiv HTML and distinguishes its 72.12% validation from 42.24% test result. `S017` no longer attributes an unreported heat-stimulus subset to the cited IEEE abstract. `S273` remains abstract-only: the currently accessible Wiley page is an abstract, and inspected retained raw artifacts are denial HTML rather than the previously claimed full text. Its DOI-resolver locator was replaced with the Wiley abstract. Exact access limits and primary locators are in EVD-03 reviews XXXV–XXXVII. An S273 Picodex job was cancelled without `agent_settled`; its output was excluded. This pass does not complete all 162 positive matrix rows.

After these edits, `scripts/check.ps1` passed with 247 sources, zero validation errors/warnings, Ruff clean and 70 pytest passes (one dependency deprecation warning). `researchctl novelty-check` remains `STOP-UNSATURATED` and `G0_REVISE`. Independent recomputation matched all 49 manifest file hashes and the aggregate digest; manifest SHA-256 is `5e69114322c6db4346f80005af806789e0ed1576c396ad5919c23b6fa4322224`. `git diff --check` found no whitespace errors. Scientific TODO remains 16/43; `EVD-03` and `SRC-08` remain open.

## S192 source-card and matrix reconciliation (28.09.2026)

The [author arXiv v3 text](https://arxiv.org/html/2409.11635v3), Figure 1 and Sections III-F and IV-A–C, identifies PainDiffusion as facial-expression generation conditioned on heat stimulus and configuration. BioVid Part C includes 87 participants split 61/26; 18 clinicians separately judged a virtual avatar, with 31.2% ± 4.8% as a perceived-realism preference rate. Reviewed batch `r4-correction-s192-generative-target-2026-09-28` corrected the source card's construct from `experimental_pain_class` to `facial_pain_expression`, populated distinct populations and the generated output label, and aligned it with matrix row 83. It does not establish pain-classification accuracy, clinical training effectiveness or therapy benefit.

`review-apply --apply` passed its integrity gate. `scripts/check.ps1` then passed with 247 sources, zero validation errors/warnings, Ruff clean and 70 pytest passes (one dependency deprecation warning). `researchctl novelty-check` retained `STOP-UNSATURATED` and `G0_REVISE`; `git diff --check` found no whitespace errors. Independent PowerShell SHA-256 checks matched all 49 release-manifest entries; aggregate digest `e9ce0c093a1b5d841a0936da74ef5a80431f75273c0d7df4d805e712829fde10`. Scientific TODO remains 16/43, with EVD-03 and SRC-08 open.

## EVD-03 rows 85–100 source-boundary review (28.09.2026)

Root and two read-only Codex reviewers examined matrix indices 85–100 at the available primary-source depth. The [PLOS Genetics text for S066](https://journals.plos.org/plosgenetics/article?id=10.1371/journal.pgen.1012122) supports a narrower RNAi caveat: the general receptor screen had uncertain knockdown efficiency, while both dedicated OAMB lines reduced expression and sensitized rolling; the VUM-targeting line labels a small secondary-abdominal-neuron subset. The [MuSACo author text for S227](https://arxiv.org/html/2508.12522) shows only a 0.1-point difference between prose and displayed rounded BioVid averages, so the matrix no longer calls it an unspecified contradiction. The [effectome JATS for S068](https://www.ebi.ac.uk/europepmc/webservices/rest/PMC11446844/fullTextXML) now has an exact Discussion Par50 locator for unavailable biological parameters. The [S030 author manuscript JATS](https://www.ebi.ac.uk/europepmc/webservices/rest/PMC5931224/fullTextXML) separates A08n necessity in the mechanical assay from sufficiency after optogenetic activation. Other checked rows retained their bounded claims; S282, S229, S222 and S026 did not acquire a new direct full-text check where current routes failed. Exact dispositions are in EVD-03 review XXXIX.

After integration, `scripts/check.ps1` passed with 247 sources, zero validation errors/warnings, Ruff clean and 70 pytest passes (one dependency deprecation warning). `researchctl novelty-check` remains `STOP-UNSATURATED` with `G0_REVISE`; `git diff --check` passed. Independent PowerShell SHA-256 checks found zero mismatches across 49 release-manifest entries; aggregate digest `2b436b211c8799f23af75c4334278d77171768a116b1e4944a93f3c335ed8b00`. Scientific TODO remains 16/43; EVD-03 and SRC-08 remain open.

## S149 version receipt, NS-06 citations and S840 source (28.09.2026)

The S149 Frontiers owner HTML captures from 27 and 28 September differ in size (2,288,942 versus 2,297,416 bytes) and SHA-256, correcting the earlier assertion that they matched byte-for-byte. The JATS captures do match. Neither pair supplies an authenticated 25 September pre-transition body, so the cause and scientific content delta of the 25-to-26 September `dateModified` shift remain unknown. The bounded matrix claims stay attached to current JATS; `SRC-08` is open. Exact receipts are in `data/src07-version-recheck-audit.json#s149_current_vor_claim_disposition_2026_09_28`.

A bounded S817 forward-citation check found two exact publisher-deposited reference edges: existing S039 and Atas et al. 2026. S039 remains an abstract-level partial analogue for subject-incremental experimental-pain recognition; ACM methods for Atas were inaccessible, so it is an identity/citation lead only. This same-day follow-up after the S836/S837 additions is not a clean saturation refresh. Exact DOI routes and limits are in `data/ns06-prior-art-audit.json#s817_forward_citation_followup_2026_09_28`; `PA-03` remains open.

The [Xu et al. bioRxiv v1 preprint in PMC](https://pmc.ncbi.nlm.nih.gov/articles/PMC12632497/) cites S839 in reference 15 and reports non-contact larval head cold avoidance, aC3da calcium activity and separate perturbations. Its head-turning endpoint is distinct from S839 body-wall contraction. After independent full-text and duplicate review, candidate S840 passed `stage` and `publish` dry runs without errors or warnings and was published with a rollback snapshot at `.work/research-snapshots/2026-09-28T015434Z-pre-publish`. The NS-03 audit now has 45 four-field extractions, with separate assay denominators and no subjective-pain or human-transfer inference. Historical 27-lead reconstruction, forward-citation saturation and S740 lineage remain open; `SRC-04` is not closed.

After integration, `scripts/check.ps1` passed with 248 sources, zero validation errors/warnings, Ruff clean and 70 pytest passes (one dependency deprecation warning). `researchctl novelty-check` retained `STOP-UNSATURATED` and `G0_REVISE`; `git diff --check` found no whitespace errors. Independent SHA-256 recomputation matched all 49 release-manifest file entries, aggregate digest `7eba4d34e0be4497f573f68cf1fd501b07857da5656f0cc692f0283291a2b6ce`. Scientific TODO remains 16/43.

## S149 saved-HTML text comparison (28.09.2026)

The two owner HTML captures still differ in raw bytes. A reproducible local extraction of the `ArticleContent` block through `</main>` found 37 versus 52 occurrences of the reference-navigation label “View reference in article”. After stripping scripts, styles, tags, whitespace variation and that UI label only, both extracted article-content strings contain 171,781 characters and have the same SHA-256 `b8f5545ef9541ad610845532119414eaec19fd450d7490c19e343553975452e9`. The comparison code is in ignored `.work/src08-next-20260928/compare_s149_html.py` and its exact method/result are recorded in the living SRC-08 audit. This narrows the 27-to-28 September text difference to reference UI labels within the inspected block; it does not compare every HTML byte or supply the missing 25 September pre-transition article. `SRC-08` remains open.

## EVD-03 source-boundary pass, indices 101–161 (28.09.2026)

Three read-only Codex reviewers checked the remaining matrix slices and recorded individual primary routes and access depths in `.work/evd03-20260928/`. The journal review XL also reconciles index 140 from its earlier direct JATS review and the prior S834 primary-text check. The one integrated correction concerns [S793's Springer Results](https://link.springer.com/article/10.1007/s40122-024-00628-z): the article calls the neural-metric denominators 236/230/254 **patients**, while the newly implanted cohort contains 148 baseline participants. Matrix row index 150 now preserves the source's unit and the unresolved cohort/scope mismatch; row index 149 retains the 65/85=77% versus Figure 1 caption 76% conflict. No patient-level ECAP-to-pain inference follows. Other rows with blocked live full text retain their previous bounded locators and are not called freshly full-text verified.

`scripts/check.ps1` passed with 248 sources, zero validation errors/warnings, Ruff clean and 70 pytest passes (one dependency deprecation warning). `researchctl novelty-check` still reports `STOP-UNSATURATED` and `G0_REVISE`. Independent SHA-256 comparison matched all 49 release-manifest entries; aggregate digest `4cbd2153bb23bad98032c19563fd2c09794fad43c0d09719b280105392a71782`. `git diff --check` found no whitespace errors. The scientific TODO remains 16/43; the full `EVD-03` criterion and SRC-08 version gate remain open.
## Интеграция EVD-03 и PA-06 от 28.09.2026

Новая проверка матрицы внесла адресные исправления `S023`, `S090`, `S189`, `S239`, `S006`, `S037`, `S086`, `S212` и `S279` с первичными локаторами в `data/evd03-evidence-matrix-audit-2026-09-25.md`. Самое существенное ограничение: LOSO у `S189` выполнен лишь на 11 из 51 участников, предварительно отобранных по subject-dependent accuracy >85%; это не оценка обобщения на полной когорте. Реестр `NCT04765735` объясняет переход 52→42 десятью выходами до рандомизации; более ранняя формулировка «необъяснённый разрыв» заменена. Карточка `S006` обновлена через проверенную партию `r5-correction-s006-metadata-boundary-2026-09-28`; полного метода по-прежнему нет.

Официальные API-записи всех 24 испытаний каталога NS-14 повторно сравнены по статусу, дате обновления и флагу опубликованных результатов: расхождений с текущим аудитом нет. Это не подтверждает доступ к индивидуальным ECAP/исходам, права повторного анализа или независимость когорт. `PA-06`, `EVD-03` и зависимый `SRC-08` остаются открытыми. Результаты двух завершившихся с ошибкой Pi-задач не приняты как проверка строк; их терминальные статусы сохранены в ignored `.work/pi-workers/df723c93-evd03-20260928-root/jobs.json`.

После интеграции `scripts/check.ps1` прошёл: 248 источников, 0 неразрешённых полей, Ruff чист, pytest 70 passed (одно предупреждение зависимости). `researchctl novelty-check` прошёл, сохранив `STOP-UNSATURATED` и `G0_REVISE`. `git diff --check` для изменённых канонических файлов прошёл. Независимая сверка всех 49 SHA-256 манифеста дала 0 несовпадений; aggregate SHA-256 `5359f06ecf1c628e0977e8a61e36c16dd832239c425478ccbe2e90a60b463311`, TODO 16/43. Это профильная проверка данного среза, не выполнение научных критериев оставшихся пунктов.

## Уточнение положительных строк EVD-03 от 28.09.2026

После сверки с [прикреплённым README DoomFly](https://github.com/nftechie/doomfly/blob/71ecf53d78eaffaf1a57ed7b0ccf5d458abc9f33/README.md), [статьёй команды Google](https://blog.google/innovation-and-ai/technology/research/male-fruit-fly-brain-map/) и [полным обзором JCDR](https://www.jcdr.net/article_fulltext.asp?id=24236&issn=0973-709x&issue=9&page=UE01&volume=20&year=2026) строки `S200`, `S368`, `S060` получили содержательные `verified_evidence` вместо общих меток `Stable source`. `S060` теперь явно обозначает синтез опубликованных работ без новой когорты. Отдельная строка `S152` ранее уточнена по полному обзору Frontiers. Датированные источники и пределы вывода записаны в `data/evd03-evidence-matrix-audit-2026-09-25.md`, раздел XLIII. Валидация прошла с 248 источниками и нулём неразрешённых полей; `scripts/check.ps1` прошёл с Ruff и 70 тестами (одно предупреждение зависимости). `researchctl novelty-check` сохранил `STOP-UNSATURATED` и `G0_REVISE`. Независимая SHA-256 сверка всех 49 файлов дала 0 несовпадений и aggregate `25388916e1d5ab19549ab4c09a1e9e84da7f6bb64c38b14ad62a4717d6cbb27a`. Научный TODO остаётся 16/43; `EVD-03` и `SRC-08` открыты.
# SRC-08: датированный срез утверждений, 28.09.2026

Независимая сверка полного прохода 81 ID показала, что девять результатов Pi были завершены и проверены, но канонический аудит первоначально содержал только состав партий и их SHA-256. В `data/src07-version-recheck-audit.json#full_81_refresh_2026_09_28.per_id_dispositions` теперь сохранены отдельные диспозиции всех 81 ID: датированный вывод, адрес карточки или отклонённого кандидата, граница первичного маршрута, влияние на включённое утверждение и SHA-256 исходного отчёта. Состав совпадает с реестром 81 ID; хеши всех девяти исходных отчётов совпали.

На проверенных доступных маршрутах на срез 28.09 новых подтверждённых событий исправления, отзыва или версии не найдено. Прежние изменения HTML `S149`, `S249`, `S231` не объяснены целиком; их включённые утверждения отдельно сверены с действующими первичными версиями и ограничены датированными диспозициями. По точному критерию TODO очередь неразобранных **включённых утверждений из-за обновления** на данном срезе равна нулю, поэтому `SRC-08` закрыт. Недоступные маршруты, уведомления вне проверенных каналов, будущие события и полная неизменность статей этим не исключены. Полная смысловая приёмка матрицы `EVD-03` остаётся открытой, шлюз `G0_REVISE`.

После обновления манифеста: `researchctl validate` и `researchctl novelty-check` прошли; последний сохранил `STOP-UNSATURATED`. `scripts/check.ps1` прошёл с 70 тестами и одним предупреждением зависимости. Отдельная сверка всех 49 SHA-256 манифеста дала ноль расхождений, `git diff --check` прошёл. Научный TODO: **17/43**.

## Адресные исправления EVD-03 и срез проверок от 28.09.2026

Партия Picodex `df723c93-1e4c-48b0-9369-b83d7952e39d-evd03-20260928-r7` завершилась: 20 из 20 заданий получили `agent_settled`, код выхода 0. Это означает получение отчётов, а не автоматическую научную приёмку каждой строки. Корневой агент отдельно сверил первичные тексты и внёс исправления для `S099`, `S060` и `S832` в карточки и доказательную матрицу; точные локаторы и границы приведены в `data/evd03-evidence-matrix-audit-2026-09-25.md`, раздел LXXXIV. Прочие отчёты этой партии остаются кандидатами на адресную сверку.

После исправления устаревшего тестового ожидания о возрастной стадии мухи в `S026` полный `scripts/check.ps1` прошёл: 248 источников, 0 ошибок и предупреждений валидации, Ruff без замечаний, pytest **70 passed** (одно предупреждение зависимости). `researchctl novelty-check` сохранил `STOP-UNSATURATED` и `G0_REVISE`. Отдельный пересчёт SHA-256 совпал со всеми 49 записями манифеста; агрегат `bd6496ef7f94a3ff53376d9d44f80145175157d30bf4e3cfcffc2e2072b7641e`. `git diff --check` для затронутых канонических файлов прошёл. Научный TODO остаётся **17/43**: смысловая проверка всех положительных строк `EVD-03` ещё не завершена.

## Дополнительная смысловая сверка EVD-03 от 28.09.2026

Три Codex-проверки отчётов Pi независимо подтвердили дополнительные исправления `S739`, `S029`, `S004`, `S193`, `S003` и `S021`; первичные локаторы и точные границы изложены в `data/evd03-evidence-matrix-audit-2026-09-25.md`, раздел LXXXVI. Недоступный в этой партии первичный полный текст `S046` не был использован для повышения статуса его результата. Срез базы: 248 карточек, 162 положительные строки матрицы и 168 уникальных ID в этих строках. Из карточек матрицы 34 ещё не имеют статуса `verified_primary`; это не число оставшихся строк для смысловой проверки, поскольку и карточки с таким статусом требуют отдельной проверки утверждений матрицы.

После правок `scripts/check.ps1` прошёл: 0 ошибок/предупреждений валидации, Ruff без замечаний, pytest **70 passed** (одно предупреждение зависимости). `researchctl novelty-check` оставил `STOP-UNSATURATED` и `G0_REVISE`. Независимая SHA-256 сверка всех 49 файлов манифеста дала 0 несовпадений, агрегат `9636de06fecc9c7f562b662ff6e395837a8d02c776815fceb675e2f8dbdbc7c8`; `git diff --check` прошёл. Научный TODO остаётся **17/43**.

## Удаление неподтверждённого тезиса S149 (28.09.2026)

Из положительной матрицы удалена строка «The imported 96% value describes this paper», поскольку её же `verified_evidence` фиксировало отсутствие такого результата в первичной статье. Отрицательная проверка и локатор сохранены в `data/evidence-review-ledger.json#s149-evidence-locator-review-2026-09-25.json` и журнале `data/evd03-evidence-matrix-audit-2026-09-25.md`, раздел LXXXVII. Подтверждённая строка S149 о синтетическом источнике остаётся. Теперь в матрице **161 положительная строка** и **168 уникальных ID** источников. `scripts/check.ps1` прошёл с нулём ошибок/предупреждений валидации, чистым Ruff и **70 passed** (одно предупреждение зависимости). `researchctl novelty-check` сохранил `STOP-UNSATURATED` и `G0_REVISE`; независимая сверка всех 49 SHA-256 манифеста дала ноль несовпадений и агрегат `1328931667f85c09a4369e246d4f06af4839a175dc906f8982373375b538abc6`. `git diff --check` прошёл. Научный TODO остаётся **17/43**.
