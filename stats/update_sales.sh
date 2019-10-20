#!/bin/bash
cd /var/lib/manamarket/stats
python /var/lib/manamarket/stats/process_salelog/main.py /var/lib/manamarket/data/logs/sale.log /var/lib/manamarket/www/manamarket.html
python /var/lib/manamarket/stats/process_salelog/main_stat.py /var/lib/manamarket/data/logs/sale.log /var/lib/manamarket/www/manamarket_stats.html
chmod 644 /var/lib/manamarket/www/manamarket.html /var/lib/manamarket/www/manamarket_stats.html
