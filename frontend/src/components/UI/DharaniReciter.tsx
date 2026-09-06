import React, { useState, useEffect, useRef, useMemo } from 'react';
import { Card, Row, Col, Tag, Button, Space, Progress, Statistic, Tooltip, message } from 'antd';
import { Play, Pause, RotateCw, Heart, Sparkles, Volume2, Bookmark, Copy, Check } from 'lucide-react';
import { audioFeedback } from '../../utils/audioFeedback';

type ChakraKey = 'heart' | 'crown' | 'third_eye' | 'throat' | 'solar_plexus' | 'sacral' | 'root';

interface Dharani {
  id: string;
  name: string;
  sanskrit: string;
  tradition: string;
  deity: string;
  mantra: string;
  chinese?: string;
  tibetan?: string;
  freq: number;
  mala: number;
  chakra: ChakraKey | string;
}

interface LogEntry {
  id: number;
  mantra: string;
  deity: string;
  count: number;
  completed: string;
  frequency: number;
}

const DHARANIS: Dharani[] = [
  {
    id: 'great_compassion',
    name: 'Great Compassion Dharani',
    sanskrit: 'Nīlakaṇṭha Dhāraṇī',
    tradition: 'Mahayana',
    deity: 'Avalokiteshvara / Chenrezig',
    mantra: 'Namo Ratna-trayāya. Namo Āryāvalokiteśvarāya Bodhisattvāya Mahāsattvāya Mahākāruṇikāya. Oṃ Sarva-rabhaye Sudhanadasya. Namo Skṛtvā Imaṃ Āryāvalokiteśvara-stavanaṃ Nīlakaṇṭha-nāma Hṛdayaṃ Vartayiṣyāmi Sarvārtha-sādhanaṃ Śubhaṃ Ajeyaṃ Sarva-bhūtānāṃ Bhava-mārga-viśodhakam. Tadyathā: Oṃ Āloka-mati Lokāti-krānta Ehi Hare Mahā-bodhisattva Sarva Sarva Smara Hṛdayam. Kuru Kuru Karma. Dhuru Dhuru Vijayate Mahā-vijayate. Dhara Dhara Dhāraṇi-rāja Cala Cala Malla-vimalāmala-mūrtte Ehy-ehi Lokeśvara Rāga-viṣa-vināśana Dveṣa-viṣa-vināśana Moha-viṣa-vināśana Huru Huru Mālā Huru Huru Hare Padmanābha Sara Sara Siri Siri Suru Suru Budhya Budhya Bodhaya Bodhaya Maitriya Nīlakaṇṭha Darśanena Prahladāya Manaḥ Svāhā. Siddhāya Svāhā. Mahā-siddhāya Svāhā. Siddhāyogeśvarāya Svāhā. Nīlakaṇṭhāya Svāhā. Vārāha-mukhāya Svāhā. Narasiṃha-mukhāya Svāhā. Padma-hastāya Svāhā. Cakra-hastāya Svāhā. Padma-gandhāya Svāhā. Śaṅkha-śabda-nibodhanāya Svāhā. Mahā-lakuṭa-dharāya Svāhā. Vāma-skandha-deśa-sthita-kṛṣṇājināya Svāhā. Vyāghra-carma-nivasanāya Svāhā. Namo Ratna-trayāya. Namo Āryāvalokiteśvarāya Svāhā. Oṃ Sidhyantu Mantra-padāni Svāhā.',
    chinese: '南無喝囉怛那哆囉夜耶。南無阿唎耶。婆盧羯帝爍缽囉耶。菩提薩埵婆耶。摩訶薩埵婆耶。摩訶迦盧尼迦耶。唵。薩皤囉罰曳。數怛那怛寫。南無悉吉栗埵伊蒙阿唎耶。婆盧吉帝室佛囉楞馱婆。南無那囉謹墀。醯唎摩訶皤哆沙咩。薩婆阿他豆輸朋。阿逝孕。薩婆薩哆那摩婆薩多那摩婆伽。摩罰特豆。怛姪他。唵阿婆盧醯。盧迦帝。迦羅帝。夷醯唎。摩訶菩提薩埵。薩婆薩婆。摩囉摩囉。摩醯摩醯唎馱孕。俱盧俱盧羯蒙。度盧度盧罰闍耶帝。摩訶罰闍耶帝。陀囉陀囉。地唎尼。室佛囉耶。遮囉遮囉。麼麼罰摩囉。穆帝隸。伊醯伊醯。室那室那。阿囉嘇佛囉舍利。罰沙罰嘇。佛囉舍耶。呼嚧呼嚧摩囉。呼嚧呼嚧醯利。娑囉娑囉。悉唎悉唎。蘇嚧蘇嚧。菩提夜菩提夜。菩馱夜菩馱夜。彌帝唎夜。那囉謹墀。地利瑟尼那。婆夜摩那。娑婆訶。悉陀夜。娑婆訶。摩訶悉陀夜。娑婆訶。悉陀喻藝。室皤囉耶。娑婆訶。那囉謹墀。娑婆訶。車囉囉蒙。娑婆訶。悉囉僧阿穆佉耶。娑婆訶。娑婆摩訶阿悉陀夜。娑婆訶。者吉囉阿悉陀夜。娑婆訶。波陀摩羯悉陀夜。娑婆訶。那囉謹墀皤伽囉耶。娑婆訶。摩婆利勝羯囉夜。娑婆訶。南無喝囉怛那哆囉夜耶。南無阿唎耶。婆嚧吉帝。爍皤囉夜。娑婆訶。唵悉殿都。漫多囉。跋陀耶。娑婆訶。',
    tibetan: 'ན་མོ་རཏྣ་ཏྲ་ཡཱ་ཡ། ན་མ་ཨཱརྱ་ཛྙཱ་ན་སཱ་ག་ར་བཻ་རོ་ཙ་ན་བྱཱུ་ཧ་རཱ་ཛཱ་ཡ། ཏ་ཐཱ་ག་ཏཱ་ཡ། ཨརྷ་ཏེ་སམྱཀ་སཾ་བུདྡྷཱ་ཡ། ན་མཿ་སརྦ་ཏ་ཐཱ་ག་ཏེ་བྷྱཿ། ཨརྷ་དྦྷྱཿ་སམྱཀ་སཾ་བུདྡྷེ་བྷྱཿ། ན་མ་ཨཱརྱཱ་ཝ་ལོ་ཀི་ཏེ་ཤྭ་རཱ་ཡ། བོ་དྷི་སཏྭཱ་ཡ། མ་ཧཱ་སཏྭཱ་ཡ། མ་ཧཱ་ཀཱ་རུ་ཎི་ཀཱ་ཡ། ཏདྱ་ཐཱ། ཨོཾ་དྷ་ར་དྷ་ར། དྷི་རི་དྷི་རི། དྷུ་རུ་དྷུ་རུ། ཨིཊྚེ་ཝིཊྚེ། ཙ་ལེ་ཙ་ལེ། པྲ་ཙ་ལེ་པྲ་ཙ་ལེ། ཀུ་སུ་མེ་ཀུ་སུ་མེ་ཝ་རེ། ཨི་ལི་མི་ལི། ཙི་ཏི་ཛྭ་ལ་མ་པ་ན་ཡ་སྭཱ་ཧཱ།',
    freq: 528,
    mala: 108,
    chakra: 'heart',
  },
  {
    id: 'ushnisha_vijaya',
    name: 'Ushnisha Vijaya Dharani',
    sanskrit: 'Uṣṇīṣa Vijaya Dhāraṇī',
    tradition: 'Mahayana',
    deity: 'Namgyalma / Ushnisha Vijaya',
    mantra: 'Namo Bhagavate Trailokya Prativiśiṣṭāya Buddhāya Bhagavate. Tadyathā: Oṃ Viśodhaya Viśodhaya, Asama-sama Samantāvabhāsa-spharaṇa Gati Gahana Svabhāva Viśuddhe, Abhiṣiñcatu Mām. Sugata Vara Vacana Amṛtābhiṣekair Mahā-mantra-padaiḥ. Āhara Āhara Āyuḥ-saṃdhāraṇi. Śodhaya Śodhaya Gagana Viśuddhe. Uṣṇīṣa Vijaya Viśuddhe Sahasra-raśmi Sañcodite. Sarva Tathāgata Avalokani Ṣaṭ-pāramitā-paripūraṇi. Sarva Tathāgata Hṛdayādhiṣṭhānādhiṣṭhita Mahā-mudre. Vajra-kāya Saṃhatana Viśuddhe. Sarvāvaraṇāpāya-durgati Pari-viśuddhe, Pratinivartaya Āyur Viśuddhe. Samayādhiṣṭhite, Maṇi Maṇi Mahā-maṇi, Tathatā Bhūta-koṭi Pariśuddhe, Visphuṭa-buddhi Śuddhe, Jaya Jaya, Vijaya Vijaya, Smara Smara, Sarva Buddhādhiṣṭhita Śuddhe, Vajre Vajra-garbhe Vajraṃ Bhavatu Mama Śarīram. Sarva Sattvānāñca Kāya Pari-viśuddhe. Sarva Gati Pariśuddhe. Sarva Tathāgata Samāśvāsādhiṣṭhite. Budhya Budhya, Bodhaya Bodhaya, Vibudhya Vibudhya, Vibodhaya Vibodhaya, Samanta Pariśuddhe. Sarva Tathāgata Hṛdayādhiṣṭhānādhiṣṭhita Mahā-mudre Svāhā.',
    chinese: '南無薄伽伐帝 帝隸路迦 鉢囉底尾始瑟吒也 勃陀也 薄伽伐帝 怛姪他 唵 尾戌馱也 尾戌馱也 娑麼娑麼 三漫哆 嚩婆娑 娑頗囉拏 揭底 誐訶曩 娑嚩婆嚩 尾秫弟 阿鼻詵左 都漫 蘇誐哆 嚩囉嚩左曩 阿蜜㗚哆 鼻曬罽 摩賀滿怛囉 鉢乃 阿賀囉 阿賀囉 阿庾散馱囉抳 戌馱也 戌馱也 誐誐曩 尾秫弟 鄔瑟膩沙 尾惹也 尾秫弟 娑賀娑囉 囉始銘 散祖禰帝 薩嚩 怛他誐哆 嚩路迦𩕳 殺吒波囉銘哆 跛哩布囉抳 薩嚩 怛他誐哆 訖哩乃野 提瑟吒曩 提瑟恥哆 摩賀母捺隸 嚩日囉迦野 僧賀哆曩 尾秫弟 薩嚩嚩囉拏 播野訥誐底 跛哩尾秫弟 鉢囉底 𩕳韈多也 阿欲秫弟 娑麼野 提瑟恥帝 麼抳 麼抳 摩賀麼抳 怛闼哆 部哆句致 跛哩秫弟 尾娑普吒 勃地秫弟 惹也 惹也 尾惹也 尾惹也 娑麼囉 娑麼囉 薩嚩 勃陀 提瑟恥哆 秫弟 嚩日隸 嚩日囉  গর্ভে 嚩日𡑞 婆嚩都 麼麼 設哩囕 薩嚩 薩怛嚩难 左 迦野 跛哩尾秫弟 薩嚩 誐底 跛哩秫弟 薩嚩 怛他誐哆 娑麼湿嚩娑 提瑟恥帝 勃地野 勃地野 冒馱野 冒馱野 尾勃地野 尾勃地野 尾冒馱野 尾冒馱野 三漫哆 跛哩秫弟 薩嚩 怛他誐哆 訖哩乃野 提瑟吒曩 提瑟恥哆 摩賀母捺隸 娑嚩賀。',
    tibetan: 'ན་མོ་བྷ་ག་ཝ་ཏེ་ཏྲཻ་ལོ་ཀྱ་པྲ་ཏི་ཝི་ཤི་ཥྚཱ་ཡ་བུདྡྷཱ་ཡ། ཏདྱ་ཐཱ། ཨོཾ་ཝི་ཤོ་དྷ་ཡ་ཝི་ཤོ་དྷ་ཡ། ཨ་ས་མ་ས་མ་ས་མནྟཱ་ཝ་བྷཱ་ས་སྥ་ར་ཎ་ག་ཏི་ག་ཧ་ན་སྭ་བྷཱ་ཝ་ཝི་ཤུདྡྷེ། ཨ་བྷི་ཥིཉྩ་ཏུ་མཱཾ། སུ་ག་ཏ་ཝ་ར་ཝ་ཙ་ན་ཨ་མྲྀ་ཏ་ཨ་བྷི་ཥེ་ཀཻ་མ་ཧཱ་མནྟྲ་པ་དཻཿ། ཨཱ་ཧ་ར་ཨཱ་ཧ་ར་ཨཱ་ཡུཿ་སནྡྷཱ་ར་ཎི། ཤོ་དྷ་ཡ་ཤོ་དྷ་ཡ་ག་ག་ན་ཝི་ཤུདྡྷེ། ཨུ་ཥྞཱི་ཥ་ཝི་ཛ་ཡ་ཝི་ཤུདྡྷེ། ས་ཧ་སྲ་རཤྨི་སཉྩོ་དི་ཏེ། སརྦ་ཏ་ཐཱ་ག་ཏཱ་ཝ་ལོ་ཀ་ནི་ཥཊ྄་པཱ་ར་མི་ཏཱ་པ་རི་པཱུ་ར་ཎི། སརྦ་ཏ་ཐཱ་ག་ཏ་མཱ་ཏི་ཏེ་ད་ཤ་བྷཱུ་མི་པྲ་ཏི་ཥྛི་ཏེ། སརྦ་ཏ་ཐཱ་ག་ཏ་ཧྲྀ་ད་ཡ་ཨ་དྷི་ཥྛཱ་ན་ཨ་དྷི་ཥྛི་ཏེ། མུ་དྲེ་མུ་དྲེ་མ་ཧཱ་མུ་དྲེ་ཝཛྲ་ཀཱ་ཡ་སཾ་ཧ་ཏ་ན་ཝི་ཤུདྡྷེ། སརྦ་ཀརྨ་ཨཱ་ཝ་ར་ཎ་ཝི་ཤུདྡྷེ། པྲ་ཏི་ནི་ཝརྟ་ཡ་ཨཱ་ཡུརྨེ་ཝི་ཤུདྡྷེ། ས་མ་ཡ་ཨ་དྷི་ཥྛི་ཏེ། མ་ཎི་མ་ཎི་མ་ཧཱ་མ་ཎི། ཏ་ཐ་ཏཱ་བྷཱུ་ཏ་ཀོ་ཊི་པ་རི་ཤུདྡྷེ། ཝི་སྥུ་ཊ་བུདྡྷི་ཤུདྡྷེ། ཛ་ཡ་ཛ་ཡ། ཝི་ཛ་ཡ་ཝི་ཛ་ཡ། སྨ་ར་སྨ་ར། སརྦ་བུདྡྷ་ཨ་དྷི་ཥྛི་ཏ་ཤུདྡྷེ། ཝཛྲི་ཝཛྲ་གརྦྷེ་ཝཛྲཾ་བྷ་ཝ་ཏུ་མ་མ་ཤ་རཱི་རཾ། སརྦ་སཏྟྭཱ་ནཱཾ་ཙ་ཀཱ་ཡ་པ་རི་ཤུདྡྷེ། སརྦ་ག་ཏི་པ་རི་ཤུདྡྷེ། སརྦ་ཏ་ཐཱ་ག་ཏ་ས་མ་ཤྭཱ་ས་ཨ་དྷི་ཥྛི་ཏེ། སརྦ་ཏ་ཐཱ་ག་ཏ་ས་མཱ་ཤྭཱ་སཱ་དྷི་ཥྛི་ཏེ། བུ་དྷྱ་བུ་དྷྱ། ཝི་བུ་དྷྱ་ཝི་བུ་དྷྱ། བོ་དྷ་ཡ་བོ་དྷ་ཡ། ཝི་བོ་དྷ་ཡ་ཝི་བོ་དྷ་ཡ། ས་མནྟ་པ་རི་ཤུདྡྷེ། སརྦ་ཏ་ཐཱ་ག་ཏ་ཧྲྀ་ད་ཡཱ་ཨ་དྷི་ཥྛཱ་ནཱ་དྷི་ཥྛི་ཏ་མ་ཧཱ་མུ་དྲེ་སྭཱ་ཧཱ།',
    freq: 741,
    mala: 108,
    chakra: 'crown',
  },
  {
    id: 'vajrasattva',
    name: 'Vajrasattva 100-Syllable Mantra',
    sanskrit: 'Vajrasattva Śatākṣara',
    tradition: 'Vajrayana',
    deity: 'Vajrasattva / Dorje Sempa',
    mantra: 'Oṃ Vajrasattva Samayam Anupālaya, Vajrasattva Tvenopatiṣṭha, Dṛḍho Me Bhava, Sutoṣyo Me Bhava, Supoṣyo Me Bhava, Anurakto Me Bhava, Sarva Siddhiṃ Me Prayaccha, Sarva Karmasu Ca Me Cittaṃ Śreyaḥ Kuru Hūṃ, Ha Ha Ha Ha Hoḥ, Bhagavān Sarva Tathāgata Vajra Mā Me Muñca, Vajrī Bhava, Mahā-samaya Sattva Āḥ Hūṃ Phaṭ Svāhā.',
    chinese: '嗡 班雜薩埵 薩瑪呀 瑪奴巴拉呀 班雜薩埵 喋諾巴 諦叉則卓 美巴哇 蘇埵卡喲 美巴哇 蘇波卡喲 美巴哇 阿奴囉多 美巴哇 薩哇悉地 美札呀叉 薩哇卡瑪 蘇雜美 漆當 喜哩揚 咕嚕 吽 哈哈哈哈 霍 拔嘎問 薩哇 達他嘎達 班雜 瑪美門雜 班唧巴哇 瑪哈薩瑪呀 薩埵 阿 吽 呸 梭哈。',
    tibetan: 'ཨོཾ་བཛྲ་སཏྭ་ས་མ་ཡ་མ་ནུ་པཱ་ལ་ཡ། བཛྲ་སཏྭ་ཏྭེ་ནོ་པ་ཏི་ཥྛ། དྲྀ་ཌྷོ་མེ་བྷ་ཝ། སུ་ཏོ་ཥྱོ་མེ་བྷ་ཝ། སུ་པོ་ཥྱོ་མེ་བྷ་ཝ། ཨ་ནུ་རཀྟོ་མེ་བྷ་ཝ། སརྦ་སིདྡྷིཾ་མེ་པྲ་ཡཙྪ། སརྦ་ཀརྨ་སུ་ཙ་མེ། ཙིཏྟཾ་ཤྲེ་ཡཿ་ཀུ་རུ་ཧཱུྃ། ཧ་ཧ་ཧ་ཧ་ཧོཿ། བྷ་ག་ཝཱན། སརྦ་ཏ་ཐཱ་ག་ཏ། བཛྲ་མཱ་མེ་མུཉྩ། བཛྲཱི་བྷ་ཝ། མ་ཧཱ་ས་མ་ཡ་སཏྭ། ཨཱཿ ཧཱུྃ་ཕཊ་སྭཱ་ཧཱ།',
    freq: 396,
    mala: 108,
    chakra: 'crown',
  },
  {
    id: 'cundi',
    name: 'Cundi Dharani (Zhunti)',
    sanskrit: 'Cundī Dhāraṇī',
    tradition: 'Mahayana',
    deity: 'Cundi Bodhisattva / Chundi',
    mantra: 'Namaḥ Saptānāṃ Samyak-saṃbuddha Koṭīnāṃ. Tadyathā: Oṃ Cale Cule Cundī Svāhā.',
    chinese: '稽首皈依蘇悉帝 頭面頂禮七俱胝 我今稱讚大準提 唯願慈悲垂加護。南無颯哆喃 三藐三勃陀 俱胝喃 怛姪他 唵 折隸 主隸 準提 娑婆訶。',
    tibetan: 'ན་མཿ སཔྟཱ་ནཱཾ སམྱཀ྄་སཾ་བུདྡྷ་ཀོ་ཊི་ནཱཾ། ཏདྱ་ཐཱ། ཨོཾ་ཙ་ལེ་ཙུ་ལེ་ཙུནྡི་སྭཱ་ཧཱ།',
    freq: 639,
    mala: 108,
    chakra: 'third_eye',
  },
  {
    id: 'medicine_buddha',
    name: 'Medicine Buddha Dharani',
    sanskrit: 'Bhaiṣajyaguru Dhāraṇī',
    tradition: 'Mahayana',
    deity: 'Medicine Buddha / Bhaisajyaguru',
    mantra: 'Namo Bhagavate Bhaiṣajyaguru Vaiḍūryaprabha-rājāya Tathāgatāya Arhate Samyak-saṃbuddhāya. Tadyathā: Oṃ Bhaiṣajye Bhaiṣajye Mahā-bhaiṣajye Bhaiṣajya-rāje Samudgate Svāhā.',
    chinese: '南無薄伽伐帝 鞞殺社 窶嚕薜琉璃 鉢喇婆 喝囉闍也 怛他揭多耶 阿囉訶諦 三藐三勃陀耶 怛姪他 唵 鞞殺逝 鞞殺逝 鞞殺社 三沒揭諦 莎訶。',
    tibetan: 'སངས་རྒྱས་སྨན་གྱི་བླ་བཻ་ཌཱུརྱའི་འོད་ཀྱི་རྒྱལ་པོ་ལ་ཕྱག་འཚལ་ལོ། ཏདྱ་ཐཱ། ཨོཾ་བྷཻ་ཥ་ཛྱེ་བྷཻ་ཥ་ཛྱེ། མ་ཧཱ་བྷཻ་ཥ་ཛྱེ། རཱ་ཛ་ས་མུདྒ་ཏེ་སྭཱ་ཧཱ།',
    freq: 528,
    mala: 108,
    chakra: 'heart',
  },
  {
    id: 'amitabha',
    name: 'Amitabha Rebirth Dharani',
    sanskrit: 'Amitābha Pure Land Dhāraṇī',
    tradition: 'Pure Land',
    deity: 'Amitabha Buddha / Opagme',
    mantra: 'Namo Amitābhāya Tathāgatāya. Tadyathā: Oṃ Amṛte Amṛtod-bhave Amṛta-sambhave Amṛta-garbhe Amṛta-siddhe Amṛta-teje Amṛta-vikrānte Amṛta-vikrānta-gāmine Amṛta-gagana-kīrti-kare Amṛta-dundubhi-svare Sarvārtha-sādhane Sarva-karma-kleśa-kṣayaṃ-kare Svāhā.',
    chinese: '南無阿彌多婆夜 哆他伽多夜 哆地夜他 阿彌利都婆毗 阿彌利哆 悉耽婆毗 阿彌唎哆 毗迦蘭帝 阿彌唎哆 毗迦蘭多 伽彌膩 伽伽那 枳多迦利 莎婆訶。',
    tibetan: 'འོད་དཔག་མེད་ཀྱི་གཟུངས།',
    freq: 963,
    mala: 108,
    chakra: 'crown',
  },
  {
    id: 'green_tara',
    name: 'Green Tara Dharani',
    sanskrit: 'Ārya Tārā Dhāraṇī',
    tradition: 'Vajrayana',
    deity: 'Green Tara / Drolma',
    mantra: 'Oṃ Tāre Tuttāre Ture Svāhā.',
    chinese: '嗡 達咧 都達咧 都咧 莎哈。',
    tibetan: 'ཨོཾ་ཏཱ་རེ་ཏུཏྟཱ་རེ་ཏུ་རེ་སྭཱ་ཧཱ།',
    freq: 639,
    mala: 108,
    chakra: 'heart',
  },
  {
    id: 'guru_rinpoche',
    name: 'Vajra Guru Mantra',
    sanskrit: 'Padmasambhava Mantra',
    tradition: 'Vajrayana',
    deity: 'Guru Rinpoche / Padmasambhava',
    mantra: 'Oṃ Āḥ Hūṃ Vajra Guru Padma Siddhi Hūṃ.',
    chinese: '嗡 阿 吽 班雜 咕嚕 貝瑪 悉地 吽。',
    tibetan: 'ཨོཾ་ཨཱཿ་ཧཱུྃ་བཛྲ་གུ་རུ་པདྨ་སིདྡྷི་ཧཱུྃ།',
    freq: 417,
    mala: 108,
    chakra: 'crown',
  },
  {
    id: 'heart_sutra',
    name: 'Heart Sutra Mantra',
    sanskrit: 'Prajñāpāramitā Hṛdaya Mantra',
    tradition: 'Mahayana',
    deity: 'Prajnaparamita / Mother of All Buddhas',
    mantra: 'Tadyathā: Gate Gate Pāragate Pārasaṃgate Bodhi Svāhā.',
    chinese: '揭諦 揭諦 波羅揭諦 波羅僧揭諦 菩提 薩婆訶。',
    tibetan: 'ཏདྱ་ཐཱ། ག་ཏེ་ག་ཏེ། པཱ་ར་ག་ཏེ། པཱ་ར་སཾ་ག་ཏེ། བོ་དྷི་སྭཱ་ཧཱ།',
    freq: 852,
    mala: 108,
    chakra: 'third_eye',
  },
  {
    id: 'manjushri',
    name: 'Manjushri Wisdom Dharani',
    sanskrit: 'Mañjuśrī Dhāraṇī',
    tradition: 'Mahayana',
    deity: 'Manjushri / Jampelyang',
    mantra: 'Oṃ A Ra Pa Ca Na Dhīḥ.',
    chinese: '嗡 阿 惹 巴 扎 那 諦。',
    tibetan: 'ཨོཾ་ཨ་ར་པ་ཙ་ན་དྷཱིཿ',
    freq: 852,
    mala: 108,
    chakra: 'third_eye',
  },
  {
    id: 'shurangama',
    name: 'Shurangama Heart Mantra & Opening',
    sanskrit: 'Śūraṅgama Mantra',
    tradition: 'Mahayana',
    deity: 'Shakyamuni Buddha (Heart Essence)',
    mantra: 'Namaḥ Sarva-tathāgatāya Sugatāya Arhate Samyak-saṃbuddhāya. Namaḥ Sarva-buddha-koṭi-uṣṇīṣebhyaḥ. Namaḥ Sarva-bodhisattvebhyaḥ Mahāsattvebhyaḥ. Tadyathā: Oṃ Anale Anale Viśade Viśade Vīra Vajra-dhare Bandha Bandhani Vajra-pāṇi Phaṭ Hūṃ Trūṃ Phaṭ Svāhā.',
    chinese: '南無薩怛他 蘇伽多耶 阿囉訶帝 三藐三菩陀寫 南無薩怛他 佛陀俱胝瑟尼釤 南無薩婆 勃陀勃地 薩跢鞞弊 南無薩多南 三藐三菩陀 俱知南 娑舍囉婆迦 僧伽喃 南無盧雞阿羅漢跢喃 南無蘇盧多波那喃 南無娑羯唎陀伽彌喃 南無盧雞三藐伽跢喃 三藐伽波囉 底波多那喃。怛姪他：唵 阿奴隸 阿奴隸 毘舍提 毘舍提 鞞囉 跋闍囉 陀唎 槃陀 槃陀你 跋闍囉 謗尼 泮 虎𤙖 都嚧甕 泮 莎婆訶。',
    tibetan: '楞嚴咒心',
    freq: 852,
    mala: 108,
    chakra: 'crown',
  },
  {
    id: 'casket_seal',
    name: 'Treasure Casket Seal Dharani',
    sanskrit: 'Guhyadhātu Karaṇḍa-mudrā Dhāraṇī',
    tradition: 'Vajrayana / Esoteric Mahayana',
    deity: 'All Tathāgatas of the Ten Directions / Vajrapāṇi',
    mantra: 'Namas tryadhvikānāṃ sarva tathāgatānām. Oṃ bhuvi-bhavana-vare vacana-vare culu culu dhara dhara, sarva tathāgata-dhātu-dhare padmaṃ-bhavati jaya-vare acale smara tathāgata dharma-cakra-pravartana vajra-bodhi-maṇḍālaṃkāra-alaṃkṛte, sarva tathāgatādhiṣṭhite, bodhaya bodhaya, bodhani bodhani, budhya budhya, saṃbodhani saṃbodhaya, cala cala calantu sarvāvaraṇāni, sarva-pāpa-vigate, huru huru sarva-śoka-vigate, sarva tathāgata-hṛdaya-vajriṇi, saṃbhava saṃbhava, sarva tathāgata-guhya-dhāraṇī-mudre, buddhe subuddhe, sarva tathāgatādhiṣṭhita-dhātu-garbhe svāhā. Samayādhiṣṭhite svāhā. Sarva tathāgata-hṛdaya-dhātu-mudre svāhā. Supratiṣṭhita-stūpe tathāgatādhiṣṭhite hūṃ hūṃ svāhā. Oṃ sarva tathāgatoṣṇīṣa-dhātu-mudrāṇi sarva tathāgata-sad-dharma-dhātu-vibhūṣitādhiṣṭhite huru huru hūṃ hūṃ svāhā.',
    chinese: '南無悉怛哩野 墜尾迦南 薩婆怛他檗多喃 唵 部尾婆嚩娜嚩唎 嚩者隸 嚩者𪘨 祖嚕祖嚕 馱囉馱囉 薩嚩怛他檗多 馱睹馱隸 鉢頭𤚥 婆嚩底 惹野嚩隸 阿左隸 麼麼 怛他檗多 達磨斫迦囉 鉢囉韈栗多曩 嚩日囉冒地滿拏 楞迦囉 楞訖哩帝 薩嚩怛他檗多 地瑟恥帝 冒馱野 冒馱野 冒地 冒地 沒亭 沒亭 參冒馱儞 參冒馱野 左攞 左攞 左懶都 薩嚩嚩囉拏儞 薩嚩播波尾檗帝 戶嚕 戶嚕 薩嚩戍迦尾檗帝 薩嚩怛他檗多 訖哩捺野 嚩日哩抳 參婆嚩 參婆嚩 薩嚩怛他檗多 虞醯野 馱囉抳 母捺隸 曀𠰢 蘇沒亭 薩嚩怛他檗多 地瑟恥多 馱睹檗陛 娑嚩賀 三摩野 地瑟恥帝 娑嚩賀 薩嚩怛他檗多 訖哩捺野 馱睹母捺隸 娑嚩賀 蘇鉢囉底瑟恥多 薩睹閉 怛他檗多 地瑟恥帝 戶嚕 戶嚕 吽 吽 娑嚩賀 唵 薩嚩怛他檗多 塢瑟膩沙 馱睹母捺囉尼 薩嚩怛他檗單 娑馱睹尾部使多 地瑟恥帝 戶嚕 戶嚕 吽 吽 娑嚩賀。',
    tibetan: 'ན་མསྟྲཻ་ཡ་དྷྭི་ཀཱ་ནཱཾ། སརྦ་ཏ་ཐཱ་ག་ཏཱ་ནཱཾ། ཨོཾ་བྷུ་ཝི་བྷ་ཝ་ན་ཝ་རེ་ཝ་ཙ་ན་ཝ་རེ། ཙུ་ལུ་ཙུ་ལུ། དྷ་ར་དྷ་ར། སརྦ་ཏ་ཐཱ་ག་ཏ་དྷཱ་ཏུ་དྷ་རེ། པདྨཾ་བྷ་ཝ་ཏི། ཛ་ཡ་ཝ་རེ། ཨ་ཙ་ལེ། སྨ་ར་ཏ་ཐཱ་ག་ཏ་དྷརྨ་ཙ་ཀྲ་པྲ་ཝརྟ་ན། ཝཛྲ་བོ་དྷི་མཎྜ་ཨ་ལཾ་ཀཱ་ར་ཨ་ལཾ་ཀྲྀ་ཏེ། སརྦ་ཏ་ཐཱ་ག་ཏ་ཨ་དྷི་ཥྛི་ཏེ། བོ་དྷ་ཡ་བོ་དྷ་ཡ། བོ་དྷ་ནི་བོ་དྷ་ནི། བུ་དྷྱ་བུ་དྷྱ། སཾ་བོ་དྷ་ནི་སཾ་བོ་དྷ་ཡ། ཙ་ལ་ཙ་ལ། ཙ་ལནྟུ་སརྦཱ་ཝ་ར་ཎཱ་ནི། སརྦ་པཱ་པ་ཝི་ག་ཏེ། ཧུ་རུ་ཧུ་རུ། སརྦ་ཤོ་ཀ་ཝི་ག་ཏེ། སརྦ་ཏ་ཐཱ་ག་ཏ་ཧྲྀ་ད་ཡ་ཝཛྲི་ཎི། སཾ་བྷ་ཝ་སཾ་བྷ་ཝ། སརྦ་ཏ་ཐཱ་ག་ཏ་གུཧྱ་དྷཱ་ར་ཎཱི་མུ་དྲེ། བུདྡྷེ་སུ་བུདྡྷེ། སརྦ་ཏ་ཐཱ་ག་ཏ་ཨ་དྷི་ཥྛི་ཏ་དྷཱ་ཏུ་གརྦྷེ་སྭཱ་ཧཱ། ས་མ་ཡ་ཨ་དྷི་ཥྛི་ཏེ་སྭཱ་ཧཱ། སརྦ་ཏ་ཐཱ་ག་ཏ་ཧྲྀ་ད་ཡ་དྷཱ་ཏུ་མུ་དྲེ་སྭཱ་ཧཱ། སུ་པྲ་ཏི་ཥྛི་ཏ་སྟཱུ་པེ་ཏ་ཐཱ་ག་ཏ་ཨ་དྷི་ཥྛི་ཏེ་ཧཱུྃ་ཧཱུྃ་སྭཱ་ཧཱ། ཨོཾ་སརྦ་ཏ་ཐཱ་ག་ཏ་ཨུ་ཥྞཱི་ཥ་དྷཱ་ཏུ་མུ་དྲཱ་ཎི། སརྦ་ཏ་ཐཱ་ག་ཏ་སདྡྷརྨ་དྷཱ་ཏུ་ཝི་བྷཱུ་ཥི་ཏ་ཨ་དྷི་ཥྛི་ཏེ་ཧུ་རུ་ཧུ་རུ་ཧཱུྃ་ཧཱུྃ་སྭཱ་ཧཱ།',
    freq: 888,
    mala: 108,
    chakra: 'crown',
  },
  {
    id: 'sitatapatra',
    name: 'Great White Canopy Dharani (Sitatapatra)',
    sanskrit: 'Sitātapatrā Dhāraṇī',
    tradition: 'Vajrayana',
    deity: 'Ushnisha Sitatapatra / White Umbrella Mother',
    mantra: 'Oṃ Sarva Tathāgatoṣṇīṣa Sitātapatre Hūṃ Phaṭ. Hūṃ Mama Hūṃ Ni Svāhā. Namo Stute Asita-analārka Prabhā-sphuṭa Vika-sitātapatre. Jvala Jvala Khāda Khāda Hana Hana Dahan Dahan Matha Matha Vidhvaṃsaya Vidhvaṃsaya Chinda Chinda Bhinda Bhinda Hūṃ Hūṃ Phaṭ Phaṭ Svāhā.',
    chinese: '南無大白傘蓋佛母。怛姪他。唵。阿奴隸。阿奴隸。毘舍提。毘舍提。鞞囉。跋闍囉。陀唎。槃陀。槃陀你。跋闍囉。謗尼。泮。虎𤙖。都嚧甕。泮。莎婆訶。唵。薩嚩。怛他檗妬瑟抳沙。悉怛多鉢怛𡃤。吽。癹吒。𤙖麼麼。𤙖。𩕳。娑嚩訶。',
    tibetan: 'ཨོཾ་སརྦ་ཏ་ཐཱ་ག་ཏོ་ཥྞཱི་ཥ་སི་ཏཱ་ཏ་པ་ཏྲེ་ཧཱུྃ་ཕཊ། ཧཱུྃ་མ་མ་ཧཱུྃ་ནི་སྭཱ་ཧཱ།',
    freq: 963,
    mala: 108,
    chakra: 'crown',
  },
  {
    id: 'mahapratisara',
    name: 'Mahapratisara Dharani (Wish-Granting)',
    sanskrit: 'Mahāpratisarā Vidyārājñī Dhāraṇī',
    tradition: 'Esoteric Mahayana',
    deity: 'Mahāpratisarā Bodhisattva',
    mantra: 'Oṃ Bhara Bhara Saṃbhara Saṃbhara Indra-viśodhani Hūṃ Hūṃ Phaṭ Phaṭ Svāhā. Oṃ Vimale Vipula-sambhave Amṛta-vare Catur-aśītī-buddha-koṭi-bhāṣite Namaḥ Sarva-tathāgatānām Oṃ Vajriṇi Vajre Mahā-vajre Vajra-pāśe Vajra-kroḍhe Amṛte Vara-vijaye Svāhā.',
    chinese: '唵。跛囉跛囉。三跛囉三跛囉。印捺哩野。尾戌馱濘。吽。吽。嚕嚕。左隸。娑嚩賀。唵。尾麼隸。尾補攞。參婆微。阿蜜㗚多。嚩隸。滿怛囉。達囉抳。莎嚩賀。',
    tibetan: 'ཨོཾ་བྷ་ར་བྷ་ར་སཾ་བྷ་ར་སཾ་བྷ་ར། ཨིནྡྲ་ཝི་ཤོ་དྷ་ནི་ཧཱུྃ་ཧཱུྃ་ཕཊ་ཕཊ་སྭཱ་ཧཱ།',
    freq: 741,
    mala: 108,
    chakra: 'throat',
  },
  {
    id: 'shurangama_full',
    name: 'Shurangama Mantra (Complete 5 Assemblies)',
    sanskrit: 'Complete Śūraṅgama Mahā-vidyā Dhāraṇī',
    tradition: 'Mahayana',
    deity: 'All Buddhas of the Ten Directions / Shakyamuni',
    mantra: 'Namaḥ Sarva Buddha Bodhisattvebhyaḥ. Namo Saptānāṃ Samyak-saṃbuddha Koṭīnāṃ Sa-śrāvaka-saṃghānām. Namo Loke Arhatānām. Namo Srotāpannānām. Namo Sakṛdāgāminām. Namo \'nāgāminām. Namo Loke Samyaggatānām. Namo Deva-ṛṣīṇām. Namo Siddha-vidyā-dhara-ṛṣīṇām. Tadyathā: Oṃ Anale Anale Viśade Viśade Vīra Vajra-dhare Bandha Bandhani Vajra-pāṇi Phaṭ Hūṃ Trūṃ Phaṭ Svāhā. Oṃ Sarva Tathāgatoṣṇīṣa-sitatapatre Hūṃ Phaṭ. Dṛḍha Bandha Bandhani Vajra-krodha Mahā-vidyā-rājñī Svāhā.',
    chinese: '【第一會：毘盧真慈】南無薩怛他。蘇伽多耶。阿囉訶帝。三藐三菩陀寫。南無薩怛他。佛陀俱胝瑟尼釤。南無薩婆。勃陀勃地。薩跢鞞弊。南無薩多南。三藐三菩陀。俱知南。娑舍囉婆迦。僧伽喃。南無盧雞阿羅漢跢喃。南無蘇盧多波那喃。南無娑羯唎陀伽彌喃。南無盧雞三藐伽跢喃。三藐伽波囉。底波多那喃。南無提婆離瑟赧。南無悉陀耶。毘地耶。陀囉離瑟赧。舍波奴。揭囉訶。娑訶娑囉摩他喃。南無跋囉訶摩泥。南無因陀囉耶。南無婆伽婆帝。嚧陀囉耶。烏摩般帝。娑醯夜耶。南無婆伽婆帝。那囉野。拏耶。槃遮摩訶。三慕陀囉。南無悉羯哩多耶。南無婆伽婆帝。摩訶迦羅耶。地唎 Nagar 婆囉拏。苾地耶。囉誓耶。南無拔折囉。俱摩唎。俱藍陀唎。南無悉羯唎多耶。南無婆伽婆帝。多他伽跢俱囉耶。南無般頭摩俱囉耶。南無跋闍囉俱囉耶。南無摩尼俱囉耶。南無伽闍俱囉耶。南無婆伽婆帝。帝哩茶。輸囉西那。波囉訶囉拏囉闍耶。跢他伽多耶。南無婆伽婆帝。南無阿彌多婆耶。跢他伽多耶。阿囉訶帝。三藐三菩陀耶。南無婆伽婆帝。阿芻鞞耶。跢他伽多耶。阿囉訶帝。三藐三菩陀耶。南無婆伽婆帝。鞞沙闍耶。俱盧吠柱唎耶。般囉婆囉闍耶。跢他伽多耶。南無婆伽婆帝。三補師毖多。薩憐捺囉剌闍耶。跢他伽多耶。阿囉訶帝。三藐三菩陀耶。南無婆伽婆帝。舍雞野母那曳。跢他伽多耶。阿囉訶帝。三藐三菩陀耶。南無婆伽婆帝。剌怛那雞都囉闍耶。跢他伽多耶。阿囉訶帝。三藐三菩陀耶。帝瓢。南無薩羯哩多。翳曇婆伽婆多。薩怛他伽都瑟尼釤。薩怛多般怛藍。南無阿婆囉視耽。般囉帝。揚岐囉。薩囉婆。部多揭囉訶。尼羯囉訶。羯迦囉訶尼。跋囉毖地耶。叱陀夜彌。鞞陀夜彌。嗔陀夜彌。槃陀夜彌。梭哈。【第二會：釋尊應化】跢姪他。唵。阿奴隸。阿奴隸。毘舍提。毘舍提。鞞囉跋闍囉陀唎。槃陀槃陀你。跋闍囉謗尼泮。虎𤙖都嚧甕泮。莎婆訶。【第三會：觀音密契】囉瑟吒耶。南無阿利耶。婆盧吉帝。爍皤囉耶。菩提薩埵耶。摩訶薩埵耶。摩訶迦盧尼迦耶。拔折囉波拏。俱盧度。摩訶迦羅。達磨達囉。阿婆囉底。揭囉訶。槃陀槃陀。梭哈。【第四會：剛藏折攝】阿跋囉底。喝多波囉。陀囉陀囉。地唎尼。室佛囉耶。遮囉遮囉。麼麼罰摩囉。穆帝隸。伊醯伊醯。室那室那。阿囉嘇佛囉舍利。罰沙罰嘇。佛囉舍耶。呼嚧呼嚧摩囉。呼嚧呼嚧醯利。娑囉娑囉。悉唎悉唎。蘇嚧蘇嚧。菩提夜菩提夜。菩馱夜菩馱夜。彌帝唎夜。娑婆訶。【第五會：文殊弘傳心咒】跢姪他。唵。阿奴隸。阿奴隸。毘舍提。毘舍提。鞞囉。跋闍囉。陀唎。槃陀。槃陀你。跋闍囉。謗尼。泮。虎𤙖。都嚧甕。泮。莎婆訶。',
    tibetan: 'ན་མཿ་སརྦ་བུདྡྷ་བོ་དྷི་སཏྭེ་བྷྱཿ། ཏདྱ་ཐཱ། ཨོཾ་ཨ་ན་ལེ་ཨ་ན་ལེ། ཝི་ཤ་དེ་ཝི་ཤ་དེ། ཝཱི་ར་ཝཛྲ་དྷཱ་རེ། བནྡྷ་བནྡྷ་ནི། ཝཛྲ་པཱ་ཎི་ཕཊ། ཧཱུྃ་ཏྲཱུྃ་ཕཊ་སྭཱ་ཧཱ།',
    freq: 852,
    mala: 108,
    chakra: 'crown',
  },
];

const CHAKRA_COLORS: Record<string, string> = {
  heart: '#22c55e',
  crown: '#a855f7',
  third_eye: '#6366f1',
  throat: '#06b6d4',
  solar_plexus: '#fbbf24',
  sacral: '#f97316',
  root: '#ef4444',
};

interface MandalaVisualProps {
  count: number;
  total: number;
  frequency: number;
  isReciting: boolean;
  chakra: ChakraKey | string;
}

// ─── Sacred Syllable Mandala ───
const MandalaVisual: React.FC<MandalaVisualProps> = ({ count, total, frequency, isReciting, chakra }) => {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const color = CHAKRA_COLORS[chakra] || '#a855f7';

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || typeof canvas.getContext !== 'function') return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;
    const w = 200, h = 200;
    ctx.clearRect(0, 0, w, h);

    // Background glow
    const grad = ctx.createRadialGradient(w / 2, h / 2, 20, w / 2, h / 2, 100);
    grad.addColorStop(0, `${color}15`);
    grad.addColorStop(1, 'transparent');
    ctx.fillStyle = grad;
    ctx.fillRect(0, 0, w, h);

    // Mala beads around perimeter
    const beads = total || 108;
    const radius = 80;
    const cx = w / 2, cy = h / 2;
    for (let i = 0; i < beads; i++) {
      const angle = (i / beads) * Math.PI * 2 - Math.PI / 2;
      const bx = cx + Math.cos(angle) * radius;
      const by = cy + Math.sin(angle) * radius;
      ctx.beginPath();
      ctx.arc(bx, by, 2, 0, Math.PI * 2);
      ctx.fillStyle = i < count ? color : '#1e293b';
      ctx.fill();
    }

    // Center glow
    const cg = ctx.createRadialGradient(cx, cy, 0, cx, cy, 30 + (count / (total || 108)) * 15);
    cg.addColorStop(0, `${color}60`);
    cg.addColorStop(1, 'transparent');
    ctx.fillStyle = cg;
    ctx.beginPath();
    ctx.arc(cx, cy, 35, 0, Math.PI * 2);
    ctx.fill();

    // Count
    ctx.fillStyle = '#fff';
    ctx.font = 'bold 22px sans-serif';
    ctx.textAlign = 'center';
    ctx.fillText(count.toString(), cx, cy + 8);

    // Frequency ring
    if (isReciting) {
      ctx.beginPath();
      ctx.arc(cx, cy, 60, 0, Math.PI * 2);
      ctx.strokeStyle = `${color}40`;
      ctx.lineWidth = 1;
      ctx.setLineDash([4, 4]);
      ctx.stroke();
      ctx.setLineDash([]);
    }
  }, [count, total, frequency, isReciting, color]);

  return <canvas ref={canvasRef} width={200} height={200} className="mx-auto" />;
};

const DharaniReciter: React.FC = () => {
  const [selected, setSelected] = useState<Dharani>(DHARANIS[0]);
  const [count, setCount] = useState(0);
  const [isReciting, setIsReciting] = useState(false);
  const [rounds, setRounds] = useState(0);
  const [log, setLog] = useState<LogEntry[]>([]);
  const [speed, setSpeed] = useState(1.5);
  const [scriptMode, setScriptMode] = useState<'sanskrit' | 'chinese' | 'tibetan'>('sanskrit');
  const [copied, setCopied] = useState(false);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const dharani = useMemo(() => selected, [selected]);
  const progress = useMemo(() => Math.round((count / (dharani.mala || 108)) * 100), [count, dharani.mala]);

  useEffect(() => {
    if (isReciting) {
      intervalRef.current = setInterval(() => {
        setCount((c) => {
          const next = c + 1;
          if (next >= (dharani.mala || 108)) {
            setRounds((r) => r + 1);
            setLog((l) => [
              {
                id: Date.now(),
                mantra: dharani.name,
                deity: dharani.deity,
                count: dharani.mala,
                completed: new Date().toLocaleTimeString(),
                frequency: dharani.freq,
              },
              ...l,
            ].slice(0, 50));
            audioFeedback.playSuccess();
            return 0;
          }
          return next;
        });
      }, 1000 / speed);
    } else {
      if (intervalRef.current) clearInterval(intervalRef.current);
    }
    return () => {
      if (intervalRef.current) clearInterval(intervalRef.current);
    };
  }, [isReciting, speed, dharani.mala, dharani.name, dharani.deity, dharani.freq]);

  const handleToggle = () => {
    audioFeedback.playClick();
    setIsReciting(!isReciting);
  };

  const handleSelectDharani = (d: Dharani) => {
    audioFeedback.playClick();
    setIsReciting(false);
    setCount(0);
    setSelected(d);
  };

  const currentDisplayText = useMemo(() => {
    if (scriptMode === 'chinese' && dharani.chinese) return dharani.chinese;
    if (scriptMode === 'tibetan' && dharani.tibetan) return dharani.tibetan;
    return dharani.mantra;
  }, [dharani, scriptMode]);

  const copyMantra = () => {
    navigator.clipboard.writeText(currentDisplayText);
    audioFeedback.playTelemetry();
    setCopied(true);
    message.success(`Copied full ${dharani.name} mantra!`);
    setTimeout(() => setCopied(false), 2000);
  };

  const totalAccumulation = useMemo(() => rounds * (dharani.mala || 108) + count, [rounds, count, dharani.mala]);
  const totalRounds = useMemo(() => log.reduce((s, l) => s + l.count, 0) + count, [log, count]);

  return (
    <div className="space-y-4">
      {/* Selector */}
      <Row gutter={[8, 8]}>
        {DHARANIS.map((d) => (
          <Col key={d.id} xs={12} sm={8} md={6}>
            <button
              type="button"
              onClick={() => handleSelectDharani(d)}
              className={`w-full text-left p-2.5 rounded-lg border transition-all text-xs ${
                selected.id === d.id
                  ? 'bg-purple-500/15 border-purple-500/50 shadow-[0_0_12px_rgba(168,85,247,0.25)]'
                  : 'bg-white/5 border-white/10 hover:border-purple-500/30'
              }`}
            >
              <div className="font-bold text-white truncate">{d.name}</div>
              <div className="text-[10px] text-slate-400 font-mono mt-0.5">{d.tradition} · {d.deity}</div>
            </button>
          </Col>
        ))}
      </Row>

      {/* Main Reciter Card */}
      <Card
        className="bg-gray-900/80 border-purple-500/20 shadow-2xl"
        styles={{ body: { padding: '24px' } }}
      >
        <Row gutter={[24, 16]} align="middle">
          {/* Mandala Visual */}
          <Col xs={24} md={9} className="flex justify-center">
            <div className="text-center">
              <MandalaVisual
                count={count}
                total={dharani.mala || 108}
                frequency={dharani.freq}
                isReciting={isReciting}
                chakra={dharani.chakra}
              />
              <Space size={4} className="mt-2">
                <Tag color="purple" className="text-[10px] font-mono">{dharani.sanskrit}</Tag>
                <Tag color="gold" className="text-[10px] font-mono">{dharani.freq} Hz</Tag>
              </Space>
            </div>
          </Col>

          {/* Controls + Info */}
          <Col xs={24} md={15}>
            <div className="space-y-4">
              {/* Header */}
              <div className="flex flex-wrap justify-between items-center gap-2">
                <div>
                  <h3 className="text-lg font-bold text-white">{dharani.name}</h3>
                  <p className="text-xs text-purple-300 font-mono mt-0.5">{dharani.deity} · {dharani.tradition}</p>
                </div>

                {/* Script Switcher */}
                <div className="flex bg-black/40 p-1 rounded-lg border border-white/10 text-[10px]">
                  <button
                    type="button"
                    onClick={() => setScriptMode('sanskrit')}
                    className={`px-2 py-1 rounded transition-colors ${
                      scriptMode === 'sanskrit' ? 'bg-purple-600 text-white font-bold' : 'text-gray-400 hover:text-white'
                    }`}
                  >
                    Sanskrit
                  </button>
                  {dharani.chinese && (
                    <button
                      type="button"
                      onClick={() => setScriptMode('chinese')}
                      className={`px-2 py-1 rounded transition-colors ${
                        scriptMode === 'chinese' ? 'bg-purple-600 text-white font-bold' : 'text-gray-400 hover:text-white'
                      }`}
                    >
                      Chinese
                    </button>
                  )}
                  {dharani.tibetan && (
                    <button
                      type="button"
                      onClick={() => setScriptMode('tibetan')}
                      className={`px-2 py-1 rounded transition-colors ${
                        scriptMode === 'tibetan' ? 'bg-purple-600 text-white font-bold' : 'text-gray-400 hover:text-white'
                      }`}
                    >
                      Tibetan
                    </button>
                  )}
                </div>
              </div>

              {/* Full Unabbreviated Mantra text container */}
              <div className="bg-black/50 rounded-xl p-4 border border-white/10 relative group">
                <div className="flex justify-between items-center mb-1.5">
                  <span className="text-[10px] font-mono uppercase text-purple-300 font-bold tracking-wider">
                    Full Unabbreviated Text ({scriptMode.toUpperCase()})
                  </span>
                  <button
                    type="button"
                    onClick={copyMantra}
                    className="text-[10px] text-gray-400 hover:text-white flex items-center gap-1 bg-white/5 hover:bg-white/10 px-2 py-0.5 rounded transition-all"
                  >
                    {copied ? <Check className="w-3 h-3 text-green-400" /> : <Copy className="w-3 h-3" />}
                    <span>{copied ? 'Copied' : 'Copy'}</span>
                  </button>
                </div>
                <div className="max-h-[180px] overflow-y-auto pr-2 scrollbar-thin scrollbar-thumb-purple-900/50">
                  <p className="text-xs text-gray-200 font-serif leading-relaxed select-text whitespace-pre-line">
                    {currentDisplayText}
                  </p>
                </div>
              </div>

              {/* Progress */}
              <div>
                <div className="flex justify-between text-[10px] text-slate-400 mb-1">
                  <span>Mala Progress</span>
                  <span className="text-purple-300 font-mono font-bold">{count}/{dharani.mala} · {progress}%</span>
                </div>
                <Progress
                  percent={progress}
                  strokeColor={{ '0%': CHAKRA_COLORS[dharani.chakra], '100%': '#a855f7' }}
                  railColor="rgba(255,255,255,0.05)"
                  showInfo={false}
                  size="small"
                />
              </div>

              {/* Stats */}
              <Row gutter={[12, 12]}>
                <Col span={8}>
                  <Statistic
                    title={<span className="text-[10px] text-slate-400 font-mono">ROUNDS</span>}
                    value={rounds}
                    valueStyle={{ color: '#a855f7', fontSize: '18px', fontWeight: 'bold' }}
                  />
                </Col>
                <Col span={8}>
                  <Statistic
                    title={<span className="text-[10px] text-slate-400 font-mono">ACCUMULATED</span>}
                    value={totalAccumulation.toLocaleString()}
                    valueStyle={{ color: '#22d3ee', fontSize: '18px', fontWeight: 'bold' }}
                  />
                </Col>
                <Col span={8}>
                  <Statistic
                    title={<span className="text-[10px] text-slate-400 font-mono">SPEED</span>}
                    value={`${speed}x`}
                    valueStyle={{ color: '#fbbf24', fontSize: '18px', fontWeight: 'bold' }}
                  />
                </Col>
              </Row>

              {/* Controls */}
              <Space size={8}>
                <Button
                  type="primary"
                  icon={isReciting ? <Pause className="w-4 h-4" /> : <Play className="w-4 h-4" />}
                  onClick={handleToggle}
                  style={{
                    background: isReciting ? '#dc2626' : 'linear-gradient(135deg, #7c3aed, #4f46e5)',
                    border: 'none',
                    fontWeight: 'bold',
                  }}
                >
                  {isReciting ? `Pause · ${count}` : 'Begin Recitation'}
                </Button>
                <Button
                  ghost
                  size="small"
                  onClick={() => {
                    audioFeedback.playClick();
                    setCount(0);
                    setIsReciting(false);
                  }}
                >
                  <RotateCw className="w-3.5 h-3.5" /> Reset
                </Button>
                <Tooltip title="Recitation speed">
                  <Button
                    ghost
                    size="small"
                    onClick={() => {
                      audioFeedback.playClick();
                      setSpeed((s) => (s >= 5 ? 0.5 : s + 0.5));
                    }}
                  >
                    {speed}x
                  </Button>
                </Tooltip>
              </Space>
            </div>
          </Col>
        </Row>
      </Card>

      {/* Accumulation Log */}
      {log.length > 0 && (
        <Card
          size="small"
          title={
            <span className="text-xs font-bold text-slate-300 font-mono uppercase tracking-wider">
              <Bookmark className="w-3.5 h-3.5 inline mr-1" />ACCUMULATION LOG
            </span>
          }
          className="bg-gray-900/80 border-purple-500/20"
          styles={{ body: { padding: '12px', maxHeight: '200px', overflowY: 'auto' } }}
        >
          <div className="space-y-1.5">
            {log.slice(0, 15).map((entry) => (
              <div
                key={entry.id}
                className="flex items-center justify-between text-[11px] px-2.5 py-1.5 bg-white/5 rounded-md border border-white/5"
              >
                <div className="flex items-center gap-2">
                  <Heart className="w-3 h-3 text-rose-400" />
                  <span className="text-white font-medium">{entry.mantra}</span>
                  <span className="text-slate-400">· {entry.deity}</span>
                </div>
                <div className="flex items-center gap-3">
                  <span className="text-purple-300 font-mono font-bold">{entry.count}×</span>
                  <span className="text-slate-500 font-mono text-[10px]">{entry.completed}</span>
                  <span className="text-[10px] text-amber-400 font-mono">{entry.frequency}Hz</span>
                </div>
              </div>
            ))}
          </div>
          <div className="text-center text-[10px] text-slate-500 mt-2 py-1 border-t border-white/5 font-mono">
            Total accumulated: {totalRounds.toLocaleString()} recitations · Dedicated to the liberation of all beings
          </div>
        </Card>
      )}
    </div>
  );
};

export default DharaniReciter;
