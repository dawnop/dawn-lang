cuda_tile.module @m {
  entry @agent_step(%arg0: tile<ptr<f64>>, %arg1: tile<ptr<f64>>) {
    %0 = make_token : token
    %1, %2, %3 = get_tile_block_id : tile<i32>
    %4 = constant <i32: 4> : tile<i32>
    %5 = muli %1, %4 : tile<i32>
    %6 = constant <i32: 0> : tile<i32>
    %7 = reshape %6 : tile<i32> -> tile<1xi32>
    %8 = broadcast %7 : tile<1xi32> -> tile<64xi32>
    %9 = iota : tile<64xi32>
    %10 = constant <i32: 4> : tile<64xi32>
    %11 = muli %9, %10 : tile<64xi32>
    %12 = addi %8, %11 : tile<64xi32>
    %13 = reshape %arg0 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %14 = broadcast %13 : tile<1xptr<f64>> -> tile<64xptr<f64>>
    %15 = offset %14, %12 : tile<64xptr<f64>>, tile<64xi32> -> tile<64xptr<f64>>
    %16, %17 = load_ptr_tko weak %15 token=%0 : tile<64xptr<f64>> -> tile<64xf64>, token
    %18 = constant <i32: 1> : tile<i32>
    %19 = reshape %18 : tile<i32> -> tile<1xi32>
    %20 = broadcast %19 : tile<1xi32> -> tile<64xi32>
    %21 = iota : tile<64xi32>
    %22 = constant <i32: 4> : tile<64xi32>
    %23 = muli %21, %22 : tile<64xi32>
    %24 = addi %20, %23 : tile<64xi32>
    %25 = reshape %arg0 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %26 = broadcast %25 : tile<1xptr<f64>> -> tile<64xptr<f64>>
    %27 = offset %26, %24 : tile<64xptr<f64>>, tile<64xi32> -> tile<64xptr<f64>>
    %28, %29 = load_ptr_tko weak %27 token=%17 : tile<64xptr<f64>> -> tile<64xf64>, token
    %30 = constant <i32: 2> : tile<i32>
    %31 = reshape %30 : tile<i32> -> tile<1xi32>
    %32 = broadcast %31 : tile<1xi32> -> tile<64xi32>
    %33 = iota : tile<64xi32>
    %34 = constant <i32: 4> : tile<64xi32>
    %35 = muli %33, %34 : tile<64xi32>
    %36 = addi %32, %35 : tile<64xi32>
    %37 = reshape %arg0 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %38 = broadcast %37 : tile<1xptr<f64>> -> tile<64xptr<f64>>
    %39 = offset %38, %36 : tile<64xptr<f64>>, tile<64xi32> -> tile<64xptr<f64>>
    %40, %41 = load_ptr_tko weak %39 token=%29 : tile<64xptr<f64>> -> tile<64xf64>, token
    %42 = constant <i32: 3> : tile<i32>
    %43 = reshape %42 : tile<i32> -> tile<1xi32>
    %44 = broadcast %43 : tile<1xi32> -> tile<64xi32>
    %45 = iota : tile<64xi32>
    %46 = constant <i32: 4> : tile<64xi32>
    %47 = muli %45, %46 : tile<64xi32>
    %48 = addi %44, %47 : tile<64xi32>
    %49 = reshape %arg0 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %50 = broadcast %49 : tile<1xptr<f64>> -> tile<64xptr<f64>>
    %51 = offset %50, %48 : tile<64xptr<f64>>, tile<64xi32> -> tile<64xptr<f64>>
    %52, %53 = load_ptr_tko weak %51 token=%41 : tile<64xptr<f64>> -> tile<64xf64>, token
    %54 = reshape %5 : tile<i32> -> tile<1xi32>
    %55 = broadcast %54 : tile<1xi32> -> tile<64xi32>
    %56 = iota : tile<64xi32>
    %57 = constant <i32: 0> : tile<64xi32>
    %58 = muli %56, %57 : tile<64xi32>
    %59 = addi %55, %58 : tile<64xi32>
    %60 = reshape %arg0 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %61 = broadcast %60 : tile<1xptr<f64>> -> tile<64xptr<f64>>
    %62 = offset %61, %59 : tile<64xptr<f64>>, tile<64xi32> -> tile<64xptr<f64>>
    %63, %64 = load_ptr_tko weak %62 token=%53 : tile<64xptr<f64>> -> tile<64xf64>, token
    %65 = constant <i32: 1> : tile<i32>
    %66 = addi %5, %65 : tile<i32>
    %67 = reshape %66 : tile<i32> -> tile<1xi32>
    %68 = broadcast %67 : tile<1xi32> -> tile<64xi32>
    %69 = iota : tile<64xi32>
    %70 = constant <i32: 0> : tile<64xi32>
    %71 = muli %69, %70 : tile<64xi32>
    %72 = addi %68, %71 : tile<64xi32>
    %73 = reshape %arg0 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %74 = broadcast %73 : tile<1xptr<f64>> -> tile<64xptr<f64>>
    %75 = offset %74, %72 : tile<64xptr<f64>>, tile<64xi32> -> tile<64xptr<f64>>
    %76, %77 = load_ptr_tko weak %75 token=%64 : tile<64xptr<f64>> -> tile<64xf64>, token
    %78 = subf %63, %16 rounding<nearest_even> : tile<64xf64>
    %79 = subf %76, %28 rounding<nearest_even> : tile<64xf64>
    %80 = mulf %78, %78 rounding<nearest_even> : tile<64xf64>
    %81 = mulf %79, %79 rounding<nearest_even> : tile<64xf64>
    %82 = addf %80, %81 rounding<nearest_even> : tile<64xf64>
    %83 = reshape %1 : tile<i32> -> tile<1xi32>
    %84 = broadcast %83 : tile<1xi32> -> tile<64xi32>
    %85 = iota : tile<64xi32>
    %86 = constant <i32: 0> : tile<64xi32>
    %87 = muli %85, %86 : tile<64xi32>
    %88 = addi %84, %87 : tile<64xi32>
    %89 = constant <i32: 0> : tile<i32>
    %90 = reshape %89 : tile<i32> -> tile<1xi32>
    %91 = broadcast %90 : tile<1xi32> -> tile<64xi32>
    %92 = iota : tile<64xi32>
    %93 = addi %91, %92 : tile<64xi32>
    %94 = cmpi equal %88, %93, signed : tile<64xi32> -> tile<64xi1>
    %95 = constant <f64: 26.0> : tile<64xf64>
    %96 = select %94, %95, %82 : tile<64xi1>, tile<64xf64>
    %97 = constant <f64: 25.0> : tile<64xf64>
    %98 = cmpf less_than ordered %96, %97 : tile<64xf64> -> tile<64xi1>
    %99 = constant <f64: 0.0> : tile<64xf64>
    %100 = select %98, %40, %99 : tile<64xi1>, tile<64xf64>
    %101 = reduce %100 dim=0 identities=[0.0 : f64] : tile<64xf64> -> tile<f64> (%102: tile<f64>, %103: tile<f64>) {
      %104 = addf %102, %103 rounding<nearest_even> : tile<f64>
      yield %104 : tile<f64>
    }
    %105 = reshape %101 : tile<f64> -> tile<1xf64>
    %106 = broadcast %105 : tile<1xf64> -> tile<1xf64>
    %107 = select %98, %52, %99 : tile<64xi1>, tile<64xf64>
    %108 = reduce %107 dim=0 identities=[0.0 : f64] : tile<64xf64> -> tile<f64> (%109: tile<f64>, %110: tile<f64>) {
      %111 = addf %109, %110 rounding<nearest_even> : tile<f64>
      yield %111 : tile<f64>
    }
    %112 = reshape %108 : tile<f64> -> tile<1xf64>
    %113 = broadcast %112 : tile<1xf64> -> tile<1xf64>
    %114 = constant <f64: 1.0> : tile<64xf64>
    %115 = select %98, %114, %99 : tile<64xi1>, tile<64xf64>
    %116 = reduce %115 dim=0 identities=[0.0 : f64] : tile<64xf64> -> tile<f64> (%117: tile<f64>, %118: tile<f64>) {
      %119 = addf %117, %118 rounding<nearest_even> : tile<f64>
      yield %119 : tile<f64>
    }
    %120 = reshape %116 : tile<f64> -> tile<1xf64>
    %121 = broadcast %120 : tile<1xf64> -> tile<1xf64>
    %122 = constant <f64: 0.0> : tile<1xf64>
    %123 = cmpf greater_than ordered %121, %122 : tile<1xf64> -> tile<1xi1>
    %124 = constant <f64: 1.0> : tile<1xf64>
    %125 = select %123, %121, %124 : tile<1xi1>, tile<1xf64>
    %126 = reshape %5 : tile<i32> -> tile<1xi32>
    %127 = broadcast %126 : tile<1xi32> -> tile<1xi32>
    %128 = iota : tile<1xi32>
    %129 = constant <i32: 0> : tile<1xi32>
    %130 = muli %128, %129 : tile<1xi32>
    %131 = addi %127, %130 : tile<1xi32>
    %132 = reshape %arg0 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %133 = broadcast %132 : tile<1xptr<f64>> -> tile<1xptr<f64>>
    %134 = offset %133, %131 : tile<1xptr<f64>>, tile<1xi32> -> tile<1xptr<f64>>
    %135, %136 = load_ptr_tko weak %134 token=%77 : tile<1xptr<f64>> -> tile<1xf64>, token
    %137 = constant <i32: 1> : tile<i32>
    %138 = addi %5, %137 : tile<i32>
    %139 = reshape %138 : tile<i32> -> tile<1xi32>
    %140 = broadcast %139 : tile<1xi32> -> tile<1xi32>
    %141 = iota : tile<1xi32>
    %142 = constant <i32: 0> : tile<1xi32>
    %143 = muli %141, %142 : tile<1xi32>
    %144 = addi %140, %143 : tile<1xi32>
    %145 = reshape %arg0 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %146 = broadcast %145 : tile<1xptr<f64>> -> tile<1xptr<f64>>
    %147 = offset %146, %144 : tile<1xptr<f64>>, tile<1xi32> -> tile<1xptr<f64>>
    %148, %149 = load_ptr_tko weak %147 token=%136 : tile<1xptr<f64>> -> tile<1xf64>, token
    %150 = constant <i32: 2> : tile<i32>
    %151 = addi %5, %150 : tile<i32>
    %152 = reshape %151 : tile<i32> -> tile<1xi32>
    %153 = broadcast %152 : tile<1xi32> -> tile<1xi32>
    %154 = iota : tile<1xi32>
    %155 = constant <i32: 0> : tile<1xi32>
    %156 = muli %154, %155 : tile<1xi32>
    %157 = addi %153, %156 : tile<1xi32>
    %158 = reshape %arg0 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %159 = broadcast %158 : tile<1xptr<f64>> -> tile<1xptr<f64>>
    %160 = offset %159, %157 : tile<1xptr<f64>>, tile<1xi32> -> tile<1xptr<f64>>
    %161, %162 = load_ptr_tko weak %160 token=%149 : tile<1xptr<f64>> -> tile<1xf64>, token
    %163 = constant <i32: 3> : tile<i32>
    %164 = addi %5, %163 : tile<i32>
    %165 = reshape %164 : tile<i32> -> tile<1xi32>
    %166 = broadcast %165 : tile<1xi32> -> tile<1xi32>
    %167 = iota : tile<1xi32>
    %168 = constant <i32: 0> : tile<1xi32>
    %169 = muli %167, %168 : tile<1xi32>
    %170 = addi %166, %169 : tile<1xi32>
    %171 = reshape %arg0 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %172 = broadcast %171 : tile<1xptr<f64>> -> tile<1xptr<f64>>
    %173 = offset %172, %170 : tile<1xptr<f64>>, tile<1xi32> -> tile<1xptr<f64>>
    %174, %175 = load_ptr_tko weak %173 token=%162 : tile<1xptr<f64>> -> tile<1xf64>, token
    %176 = divf %106, %125 rounding<nearest_even> : tile<1xf64>
    %177 = select %123, %176, %161 : tile<1xi1>, tile<1xf64>
    %178 = divf %113, %125 rounding<nearest_even> : tile<1xf64>
    %179 = select %123, %178, %174 : tile<1xi1>, tile<1xf64>
    %180 = constant <f64: 0.05> : tile<1xf64>
    %181 = subf %177, %161 rounding<nearest_even> : tile<1xf64>
    %182 = mulf %180, %181 rounding<nearest_even> : tile<1xf64>
    %183 = addf %161, %182 rounding<nearest_even> : tile<1xf64>
    %184 = subf %179, %174 rounding<nearest_even> : tile<1xf64>
    %185 = mulf %180, %184 rounding<nearest_even> : tile<1xf64>
    %186 = addf %174, %185 rounding<nearest_even> : tile<1xf64>
    %187 = addf %135, %183 rounding<nearest_even> : tile<1xf64>
    %188 = reshape %5 : tile<i32> -> tile<1xi32>
    %189 = broadcast %188 : tile<1xi32> -> tile<1xi32>
    %190 = iota : tile<1xi32>
    %191 = addi %189, %190 : tile<1xi32>
    %192 = reshape %arg1 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %193 = broadcast %192 : tile<1xptr<f64>> -> tile<1xptr<f64>>
    %194 = offset %193, %191 : tile<1xptr<f64>>, tile<1xi32> -> tile<1xptr<f64>>
    %195 = store_ptr_tko weak %194, %187 token=%175 : tile<1xptr<f64>>, tile<1xf64> -> token
    %196 = constant <i32: 1> : tile<i32>
    %197 = addi %5, %196 : tile<i32>
    %198 = addf %148, %186 rounding<nearest_even> : tile<1xf64>
    %199 = reshape %197 : tile<i32> -> tile<1xi32>
    %200 = broadcast %199 : tile<1xi32> -> tile<1xi32>
    %201 = iota : tile<1xi32>
    %202 = addi %200, %201 : tile<1xi32>
    %203 = reshape %arg1 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %204 = broadcast %203 : tile<1xptr<f64>> -> tile<1xptr<f64>>
    %205 = offset %204, %202 : tile<1xptr<f64>>, tile<1xi32> -> tile<1xptr<f64>>
    %206 = store_ptr_tko weak %205, %198 token=%195 : tile<1xptr<f64>>, tile<1xf64> -> token
    %207 = constant <i32: 2> : tile<i32>
    %208 = addi %5, %207 : tile<i32>
    %209 = reshape %208 : tile<i32> -> tile<1xi32>
    %210 = broadcast %209 : tile<1xi32> -> tile<1xi32>
    %211 = iota : tile<1xi32>
    %212 = addi %210, %211 : tile<1xi32>
    %213 = reshape %arg1 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %214 = broadcast %213 : tile<1xptr<f64>> -> tile<1xptr<f64>>
    %215 = offset %214, %212 : tile<1xptr<f64>>, tile<1xi32> -> tile<1xptr<f64>>
    %216 = store_ptr_tko weak %215, %183 token=%206 : tile<1xptr<f64>>, tile<1xf64> -> token
    %217 = constant <i32: 3> : tile<i32>
    %218 = addi %5, %217 : tile<i32>
    %219 = reshape %218 : tile<i32> -> tile<1xi32>
    %220 = broadcast %219 : tile<1xi32> -> tile<1xi32>
    %221 = iota : tile<1xi32>
    %222 = addi %220, %221 : tile<1xi32>
    %223 = reshape %arg1 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %224 = broadcast %223 : tile<1xptr<f64>> -> tile<1xptr<f64>>
    %225 = offset %224, %222 : tile<1xptr<f64>>, tile<1xi32> -> tile<1xptr<f64>>
    %226 = store_ptr_tko weak %225, %186 token=%216 : tile<1xptr<f64>>, tile<1xf64> -> token
    return
  }
}
