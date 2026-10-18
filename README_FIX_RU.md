# AI Council — исправление Android-сборки

## Что было найдено в логе

Сборка падает на этапе упаковки Python-зависимостей, а не из-за предупреждений
`dbgGenTextures` / `gil_dbgGenTextures`:

`charset_normalizer-3.5.2-cp314-cp314-android_24_arm64_v8a.whl is not a supported wheel on this platform`

В текущем workflow использовался системный Python без явного выбора версии,
а `buildozer.spec` не закреплял ветку `python-for-android`. Ошибка совпадает
с описанной в https://github.com/kivy/buildozer/issues/2051.

## Как применить

1. В своём GitHub-репозитории замени `.github/workflows/ship.yml` файлом из этого архива.
2. Замени `buildozer.spec` файлом из этого архива.
3. Сделай commit/push в ветку `main` или запусти workflow вручную через Actions.
4. Дождись завершения `build-apk`.
5. При успехе скачай артефакт `ai-council-apk`. При новом сбое скачай `ai-council-build-log` и передай лог для следующего разбора.

## Что меняется

- Явно используется Python 3.14 для соответствия `python-for-android` ветки `develop`.
- Добавлено `p4a.branch = develop` — это основной патч от ошибки wheel.
- Обновлён Android NDK до 29; `android.api = 36` и `android.minapi = 24` сохранены.
- Сохраняется журнал `buildozer.log`, даже когда сборка завершается ошибкой.

## Важное ограничение

Я проверил согласованность подготовленных файлов и сверил решение с issue,
содержащим ту же ошибку, но сам GitHub Actions не запускал. Поэтому это
исправление конфигурации, а не подтверждение, что готовый APK уже собрался.
