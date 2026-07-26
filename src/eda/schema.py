from dataclasses import dataclass , field


@dataclass
class Chunk:
    text: str
    lang : str          # "fa" | "en"

    tenant_id : str
    source : str        # "postgres.pdf"
    source_type: str    # "pdf" | "xlsx" | "image"
    location : dict     # {"type": "page", "num": 12}

    acl_groups : list[str] = field(default_factory=list)

    chunk_id : str = ""


if __name__ == '__main__':
    c = Chunk(
        text= "money is 8 bytes",
        lang= "en",
        tenant_id= "postgres",
        source= "postgres.pdf",
        source_type= "pdf",
        location= {"type" : "page" , "num" : 145},
    )
    print(c)