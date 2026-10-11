-- Таблица ФАКУЛЬТЕТЫ
CREATE TABLE ФАКУЛЬТЕТЫ (
    ID_факультета SERIAL PRIMARY KEY,
    Название_факультета VARCHAR(250) NOT NULL,
    Сокращение VARCHAR(50),
    Декан VARCHAR(150)
);
-- Таблица ПРЕПОДОВАТЕЛИ 
CREATE TABLE ПРЕПОДОВАТЕЛИ (
    ID_преподавателя SERIAL PRIMARY KEY,
    Фамилия VARCHAR(100) NOT NULL,
    ID_факультета INT REFERENCES ФАКУЛЬТЕТЫ(ID_факультета) ON DELETE SET NULL,
    Кафедра VARCHAR(250),
    Должность VARCHAR(100),
    Учёная_степень VARCHAR(150),
    Телефон VARCHAR(20),
    Паспорт VARCHAR(30)
);
-- Таблица СТУДЕНТЫ
CREATE TABLE СТУДЕНТЫ (
    ID_студента SERIAL PRIMARY KEY,
    Фамилия VARCHAR(100) NOT NULL,
    Группа VARCHAR(50),
    ID_факультета INT REFERENCES ФАКУЛЬТЕТЫ(ID_факультета) ON DELETE SET NULL,
    Год_поступления INT,
    Форма_обучения VARCHAR(50),
    Телефон VARCHAR(20),
    Паспорт VARCHAR(30)
);
-- Таблица ПРЕДМЕТЫ 
CREATE TABLE ПРЕДМЕТЫ (
    ID_предмета SERIAL PRIMARY KEY,
    Название_предмета VARCHAR(250) NOT NULL,
    ID_преподавателя INT REFERENCES ПРЕПОДОВАТЕЛИ(ID_преподавателя) ON DELETE SET NULL,
    ID_факультета INT REFERENCES ФАКУЛЬТЕТЫ(ID_факультета) ON DELETE SET NULL,
    Семестр VARCHAR(50),
    Часы INT
);
-- Таблица АБИТУРИЕНТЫ
CREATE TABLE АБИТУРИЕНТЫ (
    ID_заявления SERIAL PRIMARY KEY,
    Фамилия VARCHAR(100) NOT NULL,
    ID_факультета INT REFERENCES ФАКУЛЬТЕТЫ(ID_факультета) ON DELETE SET NULL,
    Направление VARCHAR(250),
    Год INT,
    Баллы INT,
    Телефон VARCHAR(20),
    Паспорт VARCHAR(30)
);

select * from АБИТУРИЕНТЫ;
SELECT COUNT(*) FROM АБИТУРИЕНТЫ;


-- ПРОВЕРКА
-- Кол-во записей в таблицах
SELECT 
    (SELECT COUNT(*) FROM "ФАКУЛЬТЕТЫ") AS факультеты_колво,
    (SELECT COUNT(*) FROM "ПРЕПОДОВАТЕЛИ") AS преподаватели_колво,
    (SELECT COUNT(*) FROM "ПРЕДМЕТЫ") AS предметы_колво,
    (SELECT COUNT(*) FROM "СТУДЕНТЫ") AS студенты_колво,
    (SELECT COUNT(*) FROM "АБИТУРИЕНТЫ") AS абитуриенты_колво;
-- нет студентов с несуществующими факультетами
SELECT * FROM "СТУДЕНТЫ" 
WHERE "id_факультета" NOT IN (SELECT "id_факультета" FROM "ФАКУЛЬТЕТЫ");

