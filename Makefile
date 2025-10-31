PROJECT_NAME = kaiagotchi

update_langs:
@for lang in $(PROJECT_NAME)/locale/*/; do

echo "updating language: $$lang ..."; 

./scripts/language.sh update $$(basename $$lang); 

done

compile_langs:
@for lang in $(PROJECT_NAME)/locale/*/; do

echo "compiling language: $$lang ..."; 

./scripts/language.sh compile $$(basename $$lang); 

done