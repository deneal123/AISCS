# Ноцицепция взрослой Drosophila melanogaster: проверяемый обзор для аннотации MaleCNS и планирования опыта с электрической стимуляцией и внеклеточной записью

Все утверждения ниже опираются на прочитанные источники; URL указан рядом. Где данных нет — написано «не найдено».

---

## 1. Главный вывод, без смягчений

**Доказанного ноцицептора взрослой мухи с электрической активацией не существует.** Ни одна прочитанная работа не показывает, что идентифицированный ноцицептор имаго возбуждается электрическим током. Электрический шок у взрослой дрозофилы — стандартный аверсивный стимул (60 В в ольфакторной парадигме: https://pmc.ncbi.nlm.nih.gov/articles/PMC4672959 ; 75 В в конфликтной парадигме: https://pmc.ncbi.nlm.nih.gov/articles/PMC13781089 ), но его периферический сенсор не идентифицирован. Прямая цитата: «Although the peripheral detection of electric shock remains poorly understood, central brain regions involved in its processing have been identified» (https://pmc.ncbi.nlm.nih.gov/articles/PMC13781089 ).

Единственный найденный пример, где у имаго электрически стимулируют конечность, вызывая ноцицептивный побег, и одновременно записывают нисходящий постсинаптический ответ, — Khuong et al., 2019 (https://pmc.ncbi.nlm.nih.gov/articles/PMC6620091 ). Стимулировали среднюю ногу или глаза вольфрамовыми электродами (нога: <60 В; глаза: <15 В; длительность импульса постоянно 10 мкс), записывали ПСП на мышечном волокне DLM, а не потенциал нейропиля. Это методический прецедент, но не доказательство того, что стимулируемые афференты — ноцицепторы.

Второй честный вывод: **«ноцицептор» у имаго — функциональный ярлык, а не аннотация MaleCNS.** В MaleCNS нет значения class = «nociceptive»; брюшные мультидендритные афференты лежат в class = unknown_sensory (958 нейронов / 42 типа для VNC) или mechanosensory_proprioceptive (https://raw.githubusercontent.com/dhruvin-sarkar/fault-lines/main/results/schema.md ).

---

## 2. Взрослая муха: что реально доказано

### 2.1. Центральная работа — Jones et al., 2025

Jones JM, Sustar A, Mamiya A, Walling-Bell S, Chou GM, Cook AP, Tuthill JC. «Ascending nociceptive pathways drive rapid escape and sustained avoidance in adult Drosophila». bioRxiv, 29.10.2025. doi 10.1101/2025.10.28.684868; PMID 41280033; PMCID PMC12636578. https://pmc.ncbi.nlm.nih.gov/articles/PMC12636578

Единственная найденная работа, где взрослый брюшной ноцицептор охарактеризован одновременно анатомически, оптогенетически, кальциево и коннектомно.

- **Тип клеток.** Брюшные мультидендритные нейроны, «md». Авторы прямо отказываются от ларвальной номенклатуры: «Because the class I–IV nomenclature is not used in the adult fly, we refer to the surviving class IV da neurons as abdominal multidendritic (md) neurons».
- **Число и нервы.** 30 md-нейронов на муху: 16 вентральных + 14 дорсальных, каждый покрывает один тергит или стернит на своей стороне. Аксоны входят в абдоминальный ганглий через четыре нерва: нерв 2 — 4 аксона (по 2 на сторону, сегмент 1), нерв 3 — 4 аксона, абдоминальный нервный ствол — 6 аксонов из сегментов 6/7, нерв 4 — остальные 15. В MANC реконструированы все 30.
- **Модальность.** Термическая и химическая — да; механическая — нет. In vivo двухфотонная кальциевая визуализация аксонов md в абдоминальном ганглии (md(C)-GAL4 > UAS-GCaMP7f-tdTomato, отношение зелёный/красный): металлический зонд 40 °C даёт устойчивое ΔR/R0 ≈ 0.6 на протяжении стимула (разброс ~0.2–0.8, n = 5 мух); зонд 25 °C — ответа нет; AITC (агонист TrpA1) — рост кальция. Отгибание, растяжение, сдавливание и прокалывание брюшка воспроизводимого кальциевого ответа не давали (в тексте — «data not shown»).
- **Поведение.** Оптогенетический скрининг (Chrimson, арена 10 см, ИК-видео, 30 с LED): брюшные md — единственный соматосенсорный класс, дающий одновременно быстрый побег (прыжок) и устойчивое избегание места, сохраняющееся ≥30 с после выключения света. md(C)>CsChrimson: n = 236 мух против n = 160 контролей. Остальные классы давали только кратковременный груминг или паузы.
- **Коннектом.** Все 30 аксонов md → 374 различных постсинаптических нейрона VNC (порог ≥4 синапса). 49 % синапсов аксонов md приходится на восходящие нейроны (у тактильных щетинок и проприоцепторов ног — менее 30 %). Около 73 % этих восходящих холинергические. Сами md получают преимущественно возбуждающий холинергический вход (кампановидные сенсиллы, щетинки ног, предположительно ANm-щетинки, вкусовые щетинки), а не пресинаптическое торможение, как проприоцепторы ног.
- **Восходящие драйверные линии.** SS51024 (AVLP + GNG; единственная линия с усилением прыжков; n = 369 мух по скорости, n = 441 по PI); IS35283 (GNG; n = 133 / n = 286); SS01159 (LH, SAD, AVLP, GNG; единственная линия с устойчивым избеганием места; n = 144 / n = 275).
- **Ограничение, признанное авторами.** Всё построено только на оптогенетической активации: нет теста на необходимость (сайленсинг), нет записей восходящих нейронов при естественной стимуляции.

### 2.2. Аксо-аксонное торможение — Caetano et al., 2026 (препринт, не рецензирован)

Caetano JP do C, Perez J da R, Welter FC dos S и др. «A connectomic census of axo-axonic inhibition in Drosophila: control of nociceptors is concentrated in one body-wide inhibitor». Research Square, 18.11.2026. doi 10.21203/rs.3.rs-11653602/v1; PPR1370517. https://www.researchsquare.com/article/rs-11653602/v1

Статус: Under Review, рецензирование не пройдено. Полный текст недоступен (PDF только как application/pdf), поэтому ниже — исключительно абстракт.

- Подсчитан весь синаптический вход на каждый класс сенсорных афферентов в трёх независимо полученных ЭМ-коннектомах взрослой мухи (два самца, одна самка); ГАМКергический вход разложен по пресинаптическому типу клетки.
- Три класса, терминалирующиеся в антенной доле, делят один ингибитор; каждый из семи остальных классов доминируется своим ГАМКергическим типом.
- **Ноцицептивные мультидендритные афференты имели наиболее концентрированный тормозный контроль из всех соматосенсорных классов во всех трёх животных.**
- В полном ЦНС самца одна билатеральная пара нейронов, AN05B004, даёт 57 % всего синаптического входа на ноцицепторы (против 3–20 % для крупнейшего источника на каждый механосенсорный класс).
- Каждый AN05B004 получает вход от всех 77 ноцицепторов брюшка, ног и крыльев с обеих сторон и возвращает им выход — «глобальное управление усилением».
- Медианное расстояние синапса AN05B004 до сайта выброса афферента 1.30 мкм против 7.32 мкм, ожидаемых случайно.
- В сетевой модели сайленсинг AN05B004 повышал восходящий ноцицептивный выход в 3.6 раза, не повышая глобальную активность.

Отсюда важное число: **77 ноцицепторов на самца** (брюшко + ноги + крылья) — независимая оценка, которую нужно сверить с MaleCNS.

### 2.3. Электрический шок: что известно и чего нет

- **Параметры стимула.** Классическая ольфакторная парадигма: 60 В, двенадцать импульсов по 1.25 с с межстимульным интервалом 3.75 с, суммарно 60 с, медные решётки, поток воздуха ~2 л/мин (https://pmc.ncbi.nlm.nih.gov/articles/PMC4672959 ). Конфликтная парадигма «шоковый барьер к еде»: 75 В, самцы 5–10 дней (https://pmc.ncbi.nlm.nih.gov/articles/PMC13781089 ).
- **Центральный путь.** Лейкокининовые нейроны → PV5K1 латерально-рожковые выходные нейроны → подавление шок-чувствительных FB2B нейронов вентрального вееровидного тела; использован shi-ts.
- **Ноцицептивная прослеживаемость.** Антероградный trans-Tango от painless- и trpA1-экспрессирующих ноцицепторов метит дофаминергические нейроны MB (PPL1, PAM) как прямых постсинаптических партнёров; поведение — прыжок на лазерный нагрев 473 нм, 10 мВт, пятно ~1200 мкм, вентральный торакс, окно 180 с, система ALTOMS; мутанты painless-1 и TrpA1-1 — удлинённая латентность прыжка (Yang C-L и др., bioRxiv, 04.01.2026, doi 10.64898/2026.01.04.697536; https://www.biorxiv.org/content/10.64898/2026.01.04.697536v1 ).

### 2.4. Термическая ноцицепция и центральное подавление у имаго

- Xu SY, Cang CL, Liu XF, Peng YQ, Ye YZ, Zhao ZQ, Guo AK (2006). Genes Brain Behav 5(8):602–613. PMID 17081265. https://pubmed.ncbi.nlm.nih.gov/17081265 — у имаго лазерный луч CO2, нагревающий брюшко, вызывает прыжок со стабильной латентностью; мутанты painless не избегают ноцицептивного жара. Только поведение: ни типа клеток, ни электрофизиологии.
- Neely GG, Hess A, Costigan M и др. (2011). PLoS One 6(8):e24343. PMCID PMC3164203. https://pmc.ncbi.nlm.nih.gov/articles/PMC3164203 — ~20 четырёхдневных мух в камере 35×10 мм на водяной бане 46 °C, 4 минуты; pain-1 избегают поверхности до 42 °C, но отказывают при ≥42 °C; максимум различий при 46 °C. Удаление крыльев не влияет; удаление антенн и хоботка — «modest requirement». Сайленсинг pain-GAL4 > UAS-Shi-ts1 блокирует избегание.
- Liu J, Liu W, Thakur D, Mack J, Spina A, Montell C (2023). Curr Biol 33(12):2397–2406.e6. doi 10.1016/j.cub.2023.04.055; PMCID PMC10330845; PMID 37201520. https://pmc.ncbi.nlm.nih.gov/articles/PMC10330845 — Epi-нейроны: по одному нисходящему нейрону в каждом полушарии, экспрессируют AstC и Painless, сами являются прямыми сенсорами ноцицептивного жара и подавляют термическую ноцицепцию. Метод: горячая плита 45–46 °C, процент прыжков за 10 с, крылья ампутированы за 24 ч; оптогенетика ReaChR. Лучший на сегодня пример нисходящего контроля ноцицепции у имаго.
- Gibbons M, Sarlak S, Chittka L (2022). Proc Biol Sci 289(1978):20220599. doi 10.1098/rspb.2022.0599; PMCID PMC9257290 — обзор: у насекомых, вероятно, есть нисходящий контроль ноцицепции, но отсутствуют эндогенные опиоидные пептиды и рецепторы.

### 2.5. Ларвальные работы (только механистический фон — НЕ про имаго)

Все перечисленные ниже — личинки; данных по имаго в них нет.

- Zhu M, Geng J, Sun Y, Xu L, Zhao Y, Ou M, Wang Y, Han J, Gu P, Xie W (2025). «Neurexin regulates mechanical nociceptive sensitization by central inhibition in Drosophila». Sci Adv 11(51). doi 10.1126/sciadv.adz9682; PMCID PMC12710721. https://pmc.ncbi.nlm.nih.gov/articles/PMC12710721 — потеря nrx даёт механическую ноцицептивную сенситизацию; кластер центральных холинергических нейронов SEZ назван TENCS, цепь C4da→TENCS→Goro; NRX связывает ГАМК-B-рецептор и усиливает его пресинаптическую локализацию.
- Boivin J-C, Zhao YQ, Zhu J, Dakin JT, Ning J, Ohyama T (2026). «A positive feedback loop between sensory and octopaminergic neurons underlies nociceptive plasticity in Drosophila larvae». PLoS Genet 22(4):e1012122. doi 10.1371/journal.pgen.1012122; PMID 42048383; PMCID PMC13152156 — повторная активация ларвальных C4da сенситизирует перекатывание; октопамин через OAMB; VUM-нейроны образуют положительную обратную связь на C4da.
- Palega S, Davenport H, Stewart RK, Horton J, Bellemer A (2026). «The RNA-binding protein Pumilio limits polymodal nociception in Drosophila larvae». PeerJ 14:e21481. doi 10.7717/peerj.21481; PMID 42428523; PMCID PMC13348479 — нокдаун Pumilio в ноцицепторах усиливает термическую, механическую и химическую ноцицепцию и гипералгезию после повреждения; сверхэкспрессия притупляет.

---

## 3. Анатомические идентификаторы для взрослой мухи

- Shimono K, Fujimoto A, Tsuyama T, Yamamoto-Kochi M, Sato M, Hattori Y, Takano K, Kamio M и др. (2009). Neural Dev 4:37. PMCID PMC2762467. https://pmc.ncbi.nlm.nih.gov/articles/PMC2762467 — в каждом брюшном полусомите A3/A4 шесть da-нейронов (три в тергите, три в плевре): ddaD (класс I), ddaC (класс IV), ddaE (класс I), ldaA (класс II), v'ada (класс IV) плюс ldaA-подобный; ddaE погибает caspase-зависимо в течение недели после эхлозии в A2–A4. Gal4 109(2)80 метит все da-нейроны.
- Tsubouchi A, Yano T, Yokoyama TK, Murtin C, Otsuna H, Ito K (2017). Science 358(6363):615–623. doi 10.1126/science.aan4428; PMID 29097543 — топографическая и модальность-специфичная репрезентация соматосенсорной информации; отсюда имя Amd1N.
- Онтология: adult abdominal multidendritic neuron FBbt_00048294, точный синоним Amd1N: «Mechanosensory multidendritic neuron that innervates the adult abdomen… Three innervate the dorsal region and two innervate the ventral region. Their axons project to a ventral region in the abdominal neuromere» (https://virtualflybrain.org/term/adult-abdominal-multidendritic-neuron-fbbt_00048294 ).
- adult abdominal dorsal multidendritic neuron ddaC FBbt_00048431: «…It is remodeled from the larval ddaC neuron…», в классификации — «adult multidendritic class IV neuron» (https://virtualflybrain.org/term/adult-abdominal-dorsal-multidendritic-neuron-ddac-fbbt_00048431 ).
- BANC (Bates AS, Phelps JS, Kim M, Yang HHJ, Matsliah A, Ajabi Z, Perlman E и др. (2026). Nature. doi 10.1038/s41586-026-10735-w; PMCID PMC13518251; PMID 42259917) прямо пишет: «We found sensory nociceptors from the abdomen, sensory neurons from the aorta, sensory neurons from the cibarium… oxygen-sensing neurons in the abdomen and sensory neurons from the abdominal terminalia». Мозг ~140 000, VNC ~20 000 нейронов, ~1 300 нисходящих.

**Расхождение, которое нельзя замалчивать.** FBbt_00048294 говорит о пяти нейронах на сегмент (3 дорсальных + 2 вентральных), Jones et al. — о 30 md-нейронах на муху (16 вентральных + 14 дорсальных) и 16 аксонах в нерве 4. Это разные уровни описания (онтология — на сегмент, Jones — на организм), но прямого согласования в прочитанных текстах нет.

---

## 4. Что есть в MaleCNS и как это называется

### 4.1. Схема аннотаций

Berg S, Beckett IR и др. (2026). Cell 189:5504–5526, doi 10.1016/j.cell.2026.08.019; препринт doi 10.1101/2025.10.09.680999. Полный текст: https://api.repository.cam.ac.uk/server/api/core/bitstreams/e8032e77-ba2f-42a3-a4ae-17e3cd960610/content

Цитаты: «This proofread connectome containing 124.2M synaptic connections defines a graph of 25.6M edges between 166,483 neurons (217 neurons without synapses are disconnected)»; «we defined 11,710 unique cell types»; «The coarsest annotation, 'superclass,' describes the direction of information flow, anatomical location, and broad function of neurons. Orthogonal annotations include developmental origin (hemilineage), spatial location (somaSide, somaNeuromere, entry/exitNerve), putative function (class and subclass), and names from the literature (synonyms)». Иерархия: superclass → hemilineage → supertype → type.

**Важная оговорка:** строк «receptorType», «entryNerve», «nocicept», «abdominal», «multidendritic» в тексте Cell нет. receptorType — поле базы, а не описанная в статье аннотация.

### 4.2. Реальные счётчики полей (neuPrint male-cns:v1.0)

Источник: https://raw.githubusercontent.com/dhruvin-sarkar/fault-lines/main/results/schema.md — 176 422 узла Neuron, 164 506 с типом, 11 751 различных типов.

| Поле | Заполнено у нейронов |
|---|---|
| superclass | 166 700 |
| vfbId | 166 686 |
| type | 164 506 |
| instance | 161 506 |
| somaSide | 150 726 |
| flywireType | 143 156 |
| somaLocation | 141 781 |
| supertype | 34 096 |
| hemibrainType | 32 919 |
| class | 26 513 |
| mancType | 22 744 |
| subclass | 21 930 |
| somaNeuromere | 21 820 |
| mancBodyid | 18 708 |
| rootSide | 17 939 |
| entryNerve | 11 835 |
| synonyms | 3 958 |
| matchingNotes | 3 425 |
| exitNerve | 1 005 |
| receptorType | 752 |

receptorType — «putative receptor (752 leg/wing gustatory neurons only; no Gr labels)» (https://gianlucamazza.github.io/flymsg/data.html ). Для ноцицепторов это поле отсутствует и бесполезно.

### 4.3. Значения superclass/class, релевантные задаче

| superclass | class | нейронов | типов |
|---|---|---|---|
| vnc_sensory | mechanosensory_tactile | 2 503 | 56 |
| vnc_sensory | gustatory | 1 067 | 15 |
| vnc_sensory | mechanosensory_proprioceptive | 959 | 72 |
| vnc_sensory | unknown_sensory | 958 | 42 |
| vnc_sensory | chemosensory | 48 | 2 |
| ascending_neuron | (пусто) | 1 841 | 567 |
| descending_neuron | (пусто) | 1 310 | 480 |

**Значения «nociceptive» в MaleCNS не существует ни в class, ни в subclass.**

### 4.4. Конкретные записи (проверены на VFB)

| Клетка | bodyId | Аннотации | URL |
|---|---|---|---|
| AN05B004_R | 11604 | ascending_neuron / BA / AN05B004 / AN_GNG_111 / mancType AN05B004; 67 % ГАМК; сома — абдоминальный нейромер справа; NB5-3 | https://virtualflybrain.org/term/VFB_jrmc3g4f |
| AN05B004_L | 14026 | то же, левая сторона | https://virtualflybrain.org/term/FBbt_20007723 |
| SNxx20 (брюшной md) | 806652, 803966 | vnc_sensory / unknown_sensory / abdomen / SNxx20; фасцикулирует с adult fourth abdominal nerve | https://virtualflybrain.org/term/none-malecns806652-vfb_jrmc19xc |
| SNxx07 | — | FBbt_20011303, ~35 клеток, входит через abdominal nerve trunk | https://virtualflybrain.org/term/FBbt_20011303 |
| SNxx16 / SNxx23 | — | FBbt_20011316 (~31 клетка), FBbt_20011323 (~31 клетка), abdominal nerve / abdominal nerve trunk | https://virtualflybrain.org/term/FBbt_20011316 |
| SNxx33 (нога) | 812626 | unknown_sensory / leg / SNxx33; adult metathoracic leg nerve | https://virtualflybrain.org/term/none-malecns812626-vfb_jrmc1a1x |
| SNpp02 (брюшко) | 815903 | mechanosensory_proprioceptive / abdomen / SNpp02 | https://virtualflybrain.org/term/none-malecns815903-vfb_jrmc16sq |
| SNch10 (вкусовая, нога) | 819387 | chemosensory / taste bristle | https://virtualflybrain.org/term/VFB_jrmc16q1 |

**Негативный результат, важный для аннотации:** курируемый тег VFB Nociceptive_system (https://virtualflybrain.org/tags/nociceptive_system ) содержит ~41 запись, и все они ларвальные (L1EM ID, например A08h «larval ascending neuron; larval nociceptive projection neuron»). Ни одной взрослой записи на этой странице нет. Тег на отдельных взрослых нейронах (AN09B004 — MaleCNS:574186, https://virtualflybrain.org/term/VFB_jrmc3gqf ; AN08B018 — MaleCNS:13929, https://virtualflybrain.org/term/VFB_jrmc3gjt ) наследуется по линии и физиологическим доказательством не является: в определении FlyBase FBbt:20007922 для AN09B004 слова «nociceptive» нет.

**Второе расхождение.** Caetano et al. называют AN05B004 «единственной билатеральной парой». В MaleCNS v1.0 это действительно ровно два нейрона (11604 и 14026). Но VFB для типа AN05B004 перечисляет 4 изображения, включая MANC:10327 и MANC:11670, — то есть в MANC тип представлен иначе. Считать «одна пара» универсальным фактом нельзя.

---

## 5. Внеклеточная запись LFP-подобного сигнала у насекомых

### 5.1. Что реально измеряет электрод рядом с нейропилем

Электрод в нейропиле видит сумму синаптических токов (определение LFP как «sum potentials of synaptic activity»: Stange-Marten A и др. (2026). J Comp Physiol A. doi 10.1007/s00359-026-01796-3; PMCID PMC13198461. https://pmc.ncbi.nlm.nih.gov/articles/PMC13198461 ). Вклад самих спайков выделяют фильтрацией: полоса спайков 300–5000 Гц, LFP — ниже (https://pmc.ncbi.nlm.nih.gov/articles/PMC4868374 ).

### 5.2. Числа: амплитуды и полосы

| Объект | Что записано | Амплитуда | Полоса / усиление | Источник |
|---|---|---|---|---|
| Мозг взрослой дрозофилы, покой | LFP, стеклянный электрод ~2 мкм, <1 МОм, погружение ~25–50 мкм | 2–10 мкВ RMS | Grass P15, ×1000, 0.1 Гц–10 кГц; оцифровка 20 кГц; анализ 1–55 Гц | https://pmc.ncbi.nlm.nih.gov/articles/PMC10012387 |
| То же, полёт | LFP | ~30 мкВ RMS | там же | там же |
| То же, ЭКШ-разряд | мощность LFP | медианы −32.1 / −47.7 / −61.9 dB mV2 (ЭКШ / полёт / покой) | 1/f^n, n = 0.72–1.05 в 1–55 Гц | там же |
| Мозг дрозофилы, 16-канальный зонд NeuroNexus A1x16-3mm50-177 | варианса напряжения, НЕ амплитуда ответа | 7 636.6 ± 821.0 мкВ (сырое), 1 401.1 ± 373.1 (дифференциальное), 234.0 ± 34.9 (после ICA) | импеданс 0.5–1.5 МОм; спайки >4 SD после 300–5000 Гц; линейка 200 мкВ; >2000 сайтов, >200 мух | https://pmc.ncbi.nlm.nih.gov/articles/PMC4868374 |
| Проторакальный ганглий кузнечика, МЕА на вентральной поверхности | LFP-ответы на акустику | 16.6 (12.6–30.9), 20.2 (10.2–29.8), 77.0 (39.1–101.6), 46.8 (25.3–64.5), 64.4 (46.4–98.3), 58.4 (46.4–78.9) мкВ — медиана (IQR, N = 14–16) | — | https://pmc.ncbi.nlm.nih.gov/articles/PMC13198461 |
| Поверхностный suction-электрод на нейропиле сверчка | одиночные юниты | 50–200 мкВ, шум 20–30 мкВ | ×1000, 300 Гц–5 кГц, оцифровка 21 кГц | https://pmc.ncbi.nlm.nih.gov/articles/PMC5680355 |
| Манжетный электрод на нерве таракана | нервный сигнал | 50–200 мкВ | ×1000, 250–5000 Гц, CMRR 107 dB на 200 Гц, 44.1 кГц | https://pmc.ncbi.nlm.nih.gov/articles/PMC3617879 |
| Коннективы VNC таракана, suction | спайки | «several micro-volts to millivolts»; фильтр записи 4 кГц; земля — серебро в брюшке | https://pmc.ncbi.nlm.nih.gov/articles/PMC3969889 |

**Практический вывод.** Реалистичный порядок для LFP рядом с нейропилем насекомого — десятки микровольт, а не милливольты. Сырой дрейф на 16-канальном зонде в мозге мухи — единицы милливольт, и он снимается ICA; это артефакт, а не сигнал.

### 5.3. Электрическая стимуляция: единственные найденные конкретные параметры

- Таракан, стимуляция сенсорного нерва церки: длительность 0.3 с; задержка 10 мс; частота 1 Гц; напряжение — подбирать чуть выше порога; «нет смысла заходить намного выше максимального порога, высокое напряжение повреждает нерв»; земля — в брюшке около A3; запись с перерезанного коннектива (https://pmc.ncbi.nlm.nih.gov/articles/PMC3969889 ).
- Взрослая дрозофила, стимуляция ноги: <60 В, длительность импульса постоянно 10 мкс, два вольфрамовых электрода; запись ПСП DLM вольфрамовым электродом; усилитель Model 1800, фильтр 0.5 кГц, оцифровка 1 кГц (https://pmc.ncbi.nlm.nih.gov/articles/PMC6620091 ).
- Таракан, ноцицептивные волокна: скорость проведения 2–3 м/с (медленнее тактильных), запись серебряными биполярными крючковыми электродами с коннективов, передний коннектив раздавлен для удаления нисходящей активности; усилитель A-M Systems 1700, 20 кГц, CED Micro 1401 (https://pmc.ncbi.nlm.nih.gov/articles/PMC6712093 ). Лучший методический шаблон «стимулируй брюшко — записывай восходящий канатик» у насекомого.

---

## 6. Таблица «кандидат — доказательство — как проверить»

| Кандидат (аннотация MaleCNS) | Доказательство у имаго | Пробел | Как проверить в нашей модели |
|---|---|---|---|
| Брюшные md, тип SNxx20 (MaleCNS:806652 и др.; FBbt_00048294) | Оптогенетика: побег + устойчивое избегание; кальций на 40 °C и AITC; 30 клеток, 4 нерва; 374 постсинаптических партнёра, 49 % на восходящие (Jones 2025, PMC12636578) | Нет электрической активации; нет записи восходящих при естественной стимуляции; нет теста на необходимость | Стимуляция нерва 4 или нервного ствола (по Khuong: 10 мкс, <60 В, подбор порога), запись LFP в абдоминальном нейропиле (десятки мкВ, полоса 1–100 Гц) + кальций GCaMP7f в md; контроль — сайленсинг AN05B004 |
| AN05B004_R/L (11604 / 14026) | 57 % всего входа на ноцицепторы; 1.30 мкм до сайта выброса; модель: сайленсинг ×3.6 восходящий выход (Caetano 2026, препринт) | Препринт, не рецензирован; нет физиологии; «одна пара» расходится с MANC (4 записи) | Прямая запись AN05B004 и парная запись md-аксонов; стимуляция нерва → торможение в md-терминалях; оптогенетический сайленсинг AN05B004 при тепловом стимуле |
| Восходящие AN09B004 / AN08B018 (574186 / 13929) | Только тег VFB Nociceptive_system, унаследованный по линии; в FlyBase-определении слова «nociceptive» нет | Нет ни одной физиологической публикации | Запись при стимуляции брюшка; проверить, растёт ли ответ при блокировке AN05B004 |
| SNxx07 / SNxx13 / SNxx23 (брюшной нервный ствол) | Только коннектомная аннотация (FBbt_20011303 / 20011309 / 20011323), ~35 / ~14 / ~31 клетка | Функционально не охарактеризованы | Скрининг: кальций при 40 °C, AITC, отгибании; отбор кандидатов до электрической стимуляции |
| SNxx33 / SNpp55 / SNpp61 (нога, крыло) | Только аннотации MaleCNS (подкласс leg / wing) | В список 77 ноцицепторов Caetano входят ноги и крылья, но соответствие типов не опубликовано | Стимуляция соответствующего нервного корешка (метаторакальный / мезоторакальный) |
| Epi-нейроны (нисходящие, AstC, Painless) | Прямое подавление термической ноцицепции, горячая плита 45–46 °C (Liu 2023, PMC10330845) | ID в MaleCNS в прочитанных источниках не найден | Искать пару AstC+ нисходящих в CentralBrain; активация Epi → снижение ответа на 46 °C |
| Лейкокининовые → PV5K1 → FB2B | Шок 75 В, shi-ts, конфликтная парадигма (PMC13781089) | Периферия не идентифицирована | Использовать как контроль «шок работает», не как ноцицептор |

---

## 7. Практическая рекомендация по аннотации MaleCNS

1. **Не искать class = «nociceptive»** — такого значения нет. Рабочее множество: vnc_sensory + class IN (unknown_sensory, mechanosensory_proprioceptive) + subclass = abdomen = 958 + 959 нейронов.
2. **Использовать entryNerve как главный фильтр**: «adult fourth abdominal nerve» (FBbt_00004108), «adult abdominal nerve trunk» (FBbt_00004099), «adult second abdominal nerve» (FBbt_00004106). Поле заполнено у 11 835 нейронов — самый информативный пространственный признак для сенсорных клеток без сомы в ЦНС.
3. **receptorType бесполезен** — 752 нейрона, только вкусовые ног и крыла.
4. **Ожидаемое число.** Caetano et al. называют 77 ноцицепторов (брюшко + ноги + крылья) на самца; Jones et al. — 30 брюшных md. Разница (47) должна приходиться на ноги и крылья; прямого списка типов, покрывающих эти 47, в прочитанных источниках нет — не найдено.
5. **Не наследовать тег VFB Nociceptive_system** как доказательство: он ларвальный на уровне курируемой страницы и линейный на уровне отдельных взрослых нейронов.

---

## 8. Чего в литературе нет (прямые «не найдено»)

- Не найдено ни одной работы, где идентифицированный ноцицептор взрослой дрозофилы активируется электрическим током и это показано записью.
- Не найдено ни одной работы с внеклеточной записью LFP из VNC взрослой дрозофилы (все найденные LFP — мозг: Paulk 2013, Iyengar & Wu 2021).
- Не найдено ни одной работы с patch-clamp или внеклеточной записью брюшных md-нейронов имаго; все кальциевые данные Jones et al. — оптогенетика плюс двухфотонная визуализация аксонов, не электрофизиология.
- Не найдено ни одного опубликованного соответствия «77 ноцицепторов Caetano → конкретные типы MaleCNS».
- Не найдено взрослого гомолога TENCS (ларвальный SEZ-кластер) — только ларвальные данные.
- Полный текст препринта Caetano et al. (PPR1370517) недоступен: PDF отдаётся как application/pdf, europepmc отдаёт только навигацию. Использован только абстракт.

---

## 9. Источники (все прочитаны)

1. Jones JM, Sustar A, Mamiya A, Walling-Bell S, Chou GM, Cook AP, Tuthill JC (2025). bioRxiv. doi 10.1101/2025.10.28.684868. PMID 41280033. PMC12636578.
2. Caetano JP do C и др. (2026). Research Square. doi 10.21203/rs.3.rs-11653602/v1. PPR1370517.
3. Berg S, Beckett IR и др. (2026). Cell 189:5504–5526. doi 10.1016/j.cell.2026.08.019.
4. Yang C-L и др. (2026). bioRxiv. doi 10.64898/2026.01.04.697536.
5. Liu J, Liu W, Thakur D, Mack J, Spina A, Montell C (2023). Curr Biol 33(12):2397–2406.e6. doi 10.1016/j.cub.2023.04.055.
6. Xu SY и др. (2006). Genes Brain Behav 5(8):602–613. PMID 17081265.
7. Neely GG и др. (2011). PLoS One 6(8):e24343. PMC3164203.
8. Khuong TM и др. (2019). Sci Adv 5(7):eaaw4099. PMC6620091.
9. Bodas D, Demirci S и др. (2026). Sci Adv 12(47):eaeg1944. PMC13781089.
10. Malik BR, Hodge JJL (2014). J Vis Exp (90):50107. PMC4672959.
11. Zhu M и др. (2025). Sci Adv 11(51). doi 10.1126/sciadv.adz9682. PMC12710721.
12. Boivin J-C и др. (2026). PLoS Genet 22(4):e1012122. PMC13152156.
13. Palega S и др. (2026). PeerJ 14:e21481. PMC13348479.
14. Gibbons M, Sarlak S, Chittka L (2022). Proc Biol Sci 289(1978):20220599. PMC9257290.
15. Shimono K и др. (2009). Neural Dev 4:37. PMC2762467.
16. Tsubouchi A и др. (2017). Science 358(6363):615–623. PMID 29097543.
17. Bates AS и др. (2026). Nature. doi 10.1038/s41586-026-10735-w. PMC13518251.
18. Iyengar A, Wu C-F (2021). J Neurogenet 35(3):295–305. PMC10012387.
19. Paulk AC и др. (2013). J Neurophysiol 110(7):1703–1721. PMC4868374.
20. Stange-Marten A и др. (2026). J Comp Physiol A. doi 10.1007/s00359-026-01796-3. PMC13198461.
21. Hartbauer M, Kruger TB, Stieglitz T (2012). Neurocomputing 84–178(1):3–12. PMC3617879.
22. Cooper RL и др. (2013). J Vis Exp. PMC3969889.
23. Front Physiol 10:1100 (2019). doi 10.3389/fphys.2019.01100. PMC6712093.
24. neuPrint schema male-cns:v1.0: https://raw.githubusercontent.com/dhruvin-sarkar/fault-lines/main/results/schema.md
25. flymsg data dictionary: https://gianlucamazza.github.io/flymsg/data.html
26. VFB: https://virtualflybrain.org/term/FBbt_20011316 , /FBbt_20011303 , /FBbt_00048294 , /FBbt_00048431 , /tags/nociceptive_system