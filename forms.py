from flask_wtf import FlaskForm
from wtforms import (
    StringField,
    TextAreaField,
    SelectField,
    SelectMultipleField,
    widgets,
)
from wtforms.validators import DataRequired


class MultiCheckboxField(SelectMultipleField):
    widget = widgets.ListWidget(prefix_label=False)
    option_widget = widgets.CheckboxInput()


class FolderForm(FlaskForm):
    name = StringField(
        "資料夾名稱", validators=[DataRequired(message="請輸入資料夾名稱")]
    )


class DeckForm(FlaskForm):
    name = StringField("牌組名稱", validators=[DataRequired(message="請輸入牌組名稱")])
    folders = MultiCheckboxField("所屬資料夾", coerce=int)


class EditDeckForm(DeckForm):
    card_type = SelectField(
        "學習方式（套用至牌組內所有卡片）",
        choices=[
            ("", "保留各卡片原設定"),
            ("recognize", "會背／只要認得 (recognize)"),
            ("spell", "需要會拼 (spell)"),
        ],
        default="",
    )


class CardForm(FlaskForm):
    front = StringField(
        "正面 (英文)", validators=[DataRequired(message="請輸入正面英文")]
    )
    back = TextAreaField(
        "背面 (中文)", validators=[DataRequired(message="請輸入背面中文")]
    )
    card_type = SelectField(
        "卡片類型",
        choices=[("recognize", "只要認得 (recognize)"), ("spell", "需要會拼 (spell)")],
        validators=[DataRequired()],
    )
    decks = MultiCheckboxField(
        "所屬牌組", coerce=int, validators=[DataRequired(message="請至少選擇一個牌組")]
    )


class ImportForm(FlaskForm):
    csv_text = TextAreaField(
        "CSV 內容", validators=[DataRequired(message="請輸入 CSV 內容")]
    )
    card_type = SelectField(
        "卡片類型",
        choices=[("recognize", "只要認得 (recognize)"), ("spell", "需要會拼 (spell)")],
        validators=[DataRequired()],
    )
    decks = MultiCheckboxField(
        "匯入至牌組",
        coerce=int,
        validators=[DataRequired(message="請至少選擇一個牌組")],
    )


class ExamForm(FlaskForm):
    name = StringField("考試名稱", validators=[DataRequired(message="請輸入考試名稱")])
    date = StringField(
        "考試日期與時間", validators=[DataRequired(message="請選擇考試日期與時間")]
    )
    decks = MultiCheckboxField("關聯牌組", coerce=int)
    folders = MultiCheckboxField("關聯資料夾", coerce=int)


class ExamImportForm(FlaskForm):
    csv_text = TextAreaField(
        "CSV 內容", validators=[DataRequired(message="請輸入 CSV 內容")]
    )


class EmptyForm(FlaskForm):
    pass
