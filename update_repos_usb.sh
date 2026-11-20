#!/bin/bash

# Скрипт для массового обновления репозиториев на флешке для офлайн-режима 😹

GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # Без цвета

REPOS_DIR="./repos"

# Проверяем, что мы в правильной папке
if [ ! -d "$REPOS_DIR" ]; then
    echo -e "${RED}❌ Ошибка: Папка $REPOS_DIR не найдена!${NC}"
    echo -e "Убедись, что скрипт запущен из корня папки systemd-backup на флешке 😹"
    exit 1
fi

echo -e "${BLUE}🚀 Начинаем синхронизацию репозиториев для офлайн-флешки...${NC}"
echo "==================================================="

SUCCESS=0
FAIL=0

for repo_path in "$REPOS_DIR"/*; do
    if [ -d "$repo_path" ]; then
        repo_name=$(basename "$repo_path")
        echo -e "${YELLOW}🔄 Обновляем: $repo_name${NC}"

        if [ -d "$repo_path/.git" ]; then
            cd "$repo_path" || continue

            # Делаем git pull. Если всё ок, счетчик успеха растет
            if git pull > /dev/null 2>&1; then
                echo -e "${GREEN}✅ Успешно: $repo_name${NC}"
                ((SUCCESS++))
            else
                # Если тихий pull не сработал, пробуем с выводом, чтобы было видно ошибку
                echo -e "${RED}⚠️ Пробуем обновить с выводом логов: $repo_name${NC}"
                if git pull; then
                    echo -e "${GREEN}✅ Успешно: $repo_name${NC}"
                    ((SUCCESS++))
                else
                    echo -e "${RED}❌ Ошибка обновления: $repo_name${NC}"
                    echo -e "${RED}   💡 Совет: зайди в папку и проверь git status вручную 😹${NC}"
                    ((FAIL++))
                fi
            fi
            cd - > /dev/null || exit
        else
            echo -e "${BLUE}⏭️ Пропущено (не git-репозиторий): $repo_name${NC}"
        fi
        echo "---------------------------------------------------"
    fi
done

echo "==================================================="
echo -e "${GREEN}🎉 Готово! Успешно обновлено: $SUCCESS, с ошибками: $FAIL 😹${NC}"
