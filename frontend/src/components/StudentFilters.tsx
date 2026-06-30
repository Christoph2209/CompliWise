import React from "react";

interface Props {
  search: string;
  setSearch: (value: string) => void;

  iepFilter: string;
  setIepFilter: (value: string) => void;

  tierFilter: string;
  setTierFilter: (value: string) => void;
}


export default function StudentFilters({
  search,
  setSearch,
  iepFilter,
  setIepFilter,
  tierFilter,
  setTierFilter
}: Props) {


  return (
    <div>

      <input
        placeholder="Search student..."
        value={search}
        onChange={(e) =>
          setSearch(e.target.value)
        }
      />


      <select
        value={iepFilter}
        onChange={(e) =>
          setIepFilter(e.target.value)
        }
      >

        <option value="">
          All IEP Status
        </option>

        <option value="true">
          Has IEP
        </option>

        <option value="false">
          No IEP
        </option>

      </select>



      <select
        value={tierFilter}
        onChange={(e)=>
          setTierFilter(e.target.value)
        }
      >

        <option value="">
          All MTSS Levels
        </option>

        <option value="tier_1">
          Tier 1
        </option>

        <option value="tier_2">
          Tier 2
        </option>

        <option value="tier_3">
          Tier 3
        </option>

      </select>


    </div>
  );
}