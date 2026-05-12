#!/bin/bash
cd /home/tmw/manamarket/stats
python3 /home/tmw/manamarket/stats/process_salelog/main.py      /home/tmw/manamarket/data/logs/sale.log /home/tmw/manamarket/www/manamarket.html
python3 /home/tmw/manamarket/stats/process_salelog/main_stat.py /home/tmw/manamarket/data/logs/sale.log /home/tmw/manamarket/www/manamarket_stats.html
chmod 644 /home/tmw/manamarket/www/manamarket.html /home/tmw/manamarket/www/manamarket_stats.html
