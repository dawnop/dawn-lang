cuda_tile.module @m {
  entry @attr_nan(%arg0: tile<ptr<f64>>, %arg1: tile<ptr<f64>>, %arg2: tile<ptr<f64>>) {
    %0 = make_token : token
    %1, %2, %3 = get_tile_block_id : tile<i32>
    %4 = constant <i32: 128> : tile<i32>
    %5 = muli %1, %4 : tile<i32>
    %6 = constant <i32: 2048> : tile<i32>
    %7 = muli %1, %6 : tile<i32>
    %8 = reshape %5 : tile<i32> -> tile<1xi32>
    %9 = broadcast %8 : tile<1xi32> -> tile<128xi32>
    %10 = iota : tile<128xi32>
    %11 = addi %9, %10 : tile<128xi32>
    %12 = reshape %arg0 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %13 = broadcast %12 : tile<1xptr<f64>> -> tile<128xptr<f64>>
    %14 = offset %13, %11 : tile<128xptr<f64>>, tile<128xi32> -> tile<128xptr<f64>>
    %15, %16 = load_ptr_tko weak %14 token=%0 : tile<128xptr<f64>> -> tile<128xf64>, token
    %17 = reshape %arg1 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %18 = broadcast %17 : tile<1xptr<f64>> -> tile<128xptr<f64>>
    %19 = offset %18, %11 : tile<128xptr<f64>>, tile<128xi32> -> tile<128xptr<f64>>
    %20, %21 = load_ptr_tko weak %19 token=%16 : tile<128xptr<f64>> -> tile<128xf64>, token
    %22 = cmpf equal ordered %15, %20 : tile<128xf64> -> tile<128xi1>
    %23 = exti %22 unsigned : tile<128xi1> -> tile<128xi32>
    %24 = itof %23 signed rounding<nearest_even> : tile<128xi32> -> tile<128xf64>
    %25 = reshape %7 : tile<i32> -> tile<1xi32>
    %26 = broadcast %25 : tile<1xi32> -> tile<128xi32>
    %27 = iota : tile<128xi32>
    %28 = addi %26, %27 : tile<128xi32>
    %29 = reshape %arg2 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %30 = broadcast %29 : tile<1xptr<f64>> -> tile<128xptr<f64>>
    %31 = offset %30, %28 : tile<128xptr<f64>>, tile<128xi32> -> tile<128xptr<f64>>
    %32 = store_ptr_tko weak %31, %24 token=%21 : tile<128xptr<f64>>, tile<128xf64> -> token
    %33 = constant <i32: 128> : tile<i32>
    %34 = addi %7, %33 : tile<i32>
    %35 = cmpf not_equal ordered %15, %20 : tile<128xf64> -> tile<128xi1>
    %36 = exti %35 unsigned : tile<128xi1> -> tile<128xi32>
    %37 = itof %36 signed rounding<nearest_even> : tile<128xi32> -> tile<128xf64>
    %38 = reshape %34 : tile<i32> -> tile<1xi32>
    %39 = broadcast %38 : tile<1xi32> -> tile<128xi32>
    %40 = iota : tile<128xi32>
    %41 = addi %39, %40 : tile<128xi32>
    %42 = reshape %arg2 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %43 = broadcast %42 : tile<1xptr<f64>> -> tile<128xptr<f64>>
    %44 = offset %43, %41 : tile<128xptr<f64>>, tile<128xi32> -> tile<128xptr<f64>>
    %45 = store_ptr_tko weak %44, %37 token=%32 : tile<128xptr<f64>>, tile<128xf64> -> token
    %46 = constant <i32: 256> : tile<i32>
    %47 = addi %7, %46 : tile<i32>
    %48 = cmpf less_than ordered %15, %20 : tile<128xf64> -> tile<128xi1>
    %49 = exti %48 unsigned : tile<128xi1> -> tile<128xi32>
    %50 = itof %49 signed rounding<nearest_even> : tile<128xi32> -> tile<128xf64>
    %51 = reshape %47 : tile<i32> -> tile<1xi32>
    %52 = broadcast %51 : tile<1xi32> -> tile<128xi32>
    %53 = iota : tile<128xi32>
    %54 = addi %52, %53 : tile<128xi32>
    %55 = reshape %arg2 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %56 = broadcast %55 : tile<1xptr<f64>> -> tile<128xptr<f64>>
    %57 = offset %56, %54 : tile<128xptr<f64>>, tile<128xi32> -> tile<128xptr<f64>>
    %58 = store_ptr_tko weak %57, %50 token=%45 : tile<128xptr<f64>>, tile<128xf64> -> token
    %59 = constant <i32: 384> : tile<i32>
    %60 = addi %7, %59 : tile<i32>
    %61 = cmpf less_than_or_equal ordered %15, %20 : tile<128xf64> -> tile<128xi1>
    %62 = exti %61 unsigned : tile<128xi1> -> tile<128xi32>
    %63 = itof %62 signed rounding<nearest_even> : tile<128xi32> -> tile<128xf64>
    %64 = reshape %60 : tile<i32> -> tile<1xi32>
    %65 = broadcast %64 : tile<1xi32> -> tile<128xi32>
    %66 = iota : tile<128xi32>
    %67 = addi %65, %66 : tile<128xi32>
    %68 = reshape %arg2 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %69 = broadcast %68 : tile<1xptr<f64>> -> tile<128xptr<f64>>
    %70 = offset %69, %67 : tile<128xptr<f64>>, tile<128xi32> -> tile<128xptr<f64>>
    %71 = store_ptr_tko weak %70, %63 token=%58 : tile<128xptr<f64>>, tile<128xf64> -> token
    %72 = constant <i32: 512> : tile<i32>
    %73 = addi %7, %72 : tile<i32>
    %74 = cmpf greater_than ordered %15, %20 : tile<128xf64> -> tile<128xi1>
    %75 = exti %74 unsigned : tile<128xi1> -> tile<128xi32>
    %76 = itof %75 signed rounding<nearest_even> : tile<128xi32> -> tile<128xf64>
    %77 = reshape %73 : tile<i32> -> tile<1xi32>
    %78 = broadcast %77 : tile<1xi32> -> tile<128xi32>
    %79 = iota : tile<128xi32>
    %80 = addi %78, %79 : tile<128xi32>
    %81 = reshape %arg2 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %82 = broadcast %81 : tile<1xptr<f64>> -> tile<128xptr<f64>>
    %83 = offset %82, %80 : tile<128xptr<f64>>, tile<128xi32> -> tile<128xptr<f64>>
    %84 = store_ptr_tko weak %83, %76 token=%71 : tile<128xptr<f64>>, tile<128xf64> -> token
    %85 = constant <i32: 640> : tile<i32>
    %86 = addi %7, %85 : tile<i32>
    %87 = cmpf greater_than_or_equal ordered %15, %20 : tile<128xf64> -> tile<128xi1>
    %88 = exti %87 unsigned : tile<128xi1> -> tile<128xi32>
    %89 = itof %88 signed rounding<nearest_even> : tile<128xi32> -> tile<128xf64>
    %90 = reshape %86 : tile<i32> -> tile<1xi32>
    %91 = broadcast %90 : tile<1xi32> -> tile<128xi32>
    %92 = iota : tile<128xi32>
    %93 = addi %91, %92 : tile<128xi32>
    %94 = reshape %arg2 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %95 = broadcast %94 : tile<1xptr<f64>> -> tile<128xptr<f64>>
    %96 = offset %95, %93 : tile<128xptr<f64>>, tile<128xi32> -> tile<128xptr<f64>>
    %97 = store_ptr_tko weak %96, %89 token=%84 : tile<128xptr<f64>>, tile<128xf64> -> token
    %98 = constant <i32: 768> : tile<i32>
    %99 = addi %7, %98 : tile<i32>
    %100 = cmpf equal unordered %15, %20 : tile<128xf64> -> tile<128xi1>
    %101 = exti %100 unsigned : tile<128xi1> -> tile<128xi32>
    %102 = itof %101 signed rounding<nearest_even> : tile<128xi32> -> tile<128xf64>
    %103 = reshape %99 : tile<i32> -> tile<1xi32>
    %104 = broadcast %103 : tile<1xi32> -> tile<128xi32>
    %105 = iota : tile<128xi32>
    %106 = addi %104, %105 : tile<128xi32>
    %107 = reshape %arg2 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %108 = broadcast %107 : tile<1xptr<f64>> -> tile<128xptr<f64>>
    %109 = offset %108, %106 : tile<128xptr<f64>>, tile<128xi32> -> tile<128xptr<f64>>
    %110 = store_ptr_tko weak %109, %102 token=%97 : tile<128xptr<f64>>, tile<128xf64> -> token
    %111 = constant <i32: 896> : tile<i32>
    %112 = addi %7, %111 : tile<i32>
    %113 = cmpf not_equal unordered %15, %20 : tile<128xf64> -> tile<128xi1>
    %114 = exti %113 unsigned : tile<128xi1> -> tile<128xi32>
    %115 = itof %114 signed rounding<nearest_even> : tile<128xi32> -> tile<128xf64>
    %116 = reshape %112 : tile<i32> -> tile<1xi32>
    %117 = broadcast %116 : tile<1xi32> -> tile<128xi32>
    %118 = iota : tile<128xi32>
    %119 = addi %117, %118 : tile<128xi32>
    %120 = reshape %arg2 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %121 = broadcast %120 : tile<1xptr<f64>> -> tile<128xptr<f64>>
    %122 = offset %121, %119 : tile<128xptr<f64>>, tile<128xi32> -> tile<128xptr<f64>>
    %123 = store_ptr_tko weak %122, %115 token=%110 : tile<128xptr<f64>>, tile<128xf64> -> token
    %124 = constant <i32: 1024> : tile<i32>
    %125 = addi %7, %124 : tile<i32>
    %126 = cmpf less_than unordered %15, %20 : tile<128xf64> -> tile<128xi1>
    %127 = exti %126 unsigned : tile<128xi1> -> tile<128xi32>
    %128 = itof %127 signed rounding<nearest_even> : tile<128xi32> -> tile<128xf64>
    %129 = reshape %125 : tile<i32> -> tile<1xi32>
    %130 = broadcast %129 : tile<1xi32> -> tile<128xi32>
    %131 = iota : tile<128xi32>
    %132 = addi %130, %131 : tile<128xi32>
    %133 = reshape %arg2 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %134 = broadcast %133 : tile<1xptr<f64>> -> tile<128xptr<f64>>
    %135 = offset %134, %132 : tile<128xptr<f64>>, tile<128xi32> -> tile<128xptr<f64>>
    %136 = store_ptr_tko weak %135, %128 token=%123 : tile<128xptr<f64>>, tile<128xf64> -> token
    %137 = constant <i32: 1152> : tile<i32>
    %138 = addi %7, %137 : tile<i32>
    %139 = cmpf less_than_or_equal unordered %15, %20 : tile<128xf64> -> tile<128xi1>
    %140 = exti %139 unsigned : tile<128xi1> -> tile<128xi32>
    %141 = itof %140 signed rounding<nearest_even> : tile<128xi32> -> tile<128xf64>
    %142 = reshape %138 : tile<i32> -> tile<1xi32>
    %143 = broadcast %142 : tile<1xi32> -> tile<128xi32>
    %144 = iota : tile<128xi32>
    %145 = addi %143, %144 : tile<128xi32>
    %146 = reshape %arg2 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %147 = broadcast %146 : tile<1xptr<f64>> -> tile<128xptr<f64>>
    %148 = offset %147, %145 : tile<128xptr<f64>>, tile<128xi32> -> tile<128xptr<f64>>
    %149 = store_ptr_tko weak %148, %141 token=%136 : tile<128xptr<f64>>, tile<128xf64> -> token
    %150 = constant <i32: 1280> : tile<i32>
    %151 = addi %7, %150 : tile<i32>
    %152 = cmpf greater_than unordered %15, %20 : tile<128xf64> -> tile<128xi1>
    %153 = exti %152 unsigned : tile<128xi1> -> tile<128xi32>
    %154 = itof %153 signed rounding<nearest_even> : tile<128xi32> -> tile<128xf64>
    %155 = reshape %151 : tile<i32> -> tile<1xi32>
    %156 = broadcast %155 : tile<1xi32> -> tile<128xi32>
    %157 = iota : tile<128xi32>
    %158 = addi %156, %157 : tile<128xi32>
    %159 = reshape %arg2 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %160 = broadcast %159 : tile<1xptr<f64>> -> tile<128xptr<f64>>
    %161 = offset %160, %158 : tile<128xptr<f64>>, tile<128xi32> -> tile<128xptr<f64>>
    %162 = store_ptr_tko weak %161, %154 token=%149 : tile<128xptr<f64>>, tile<128xf64> -> token
    %163 = constant <i32: 1408> : tile<i32>
    %164 = addi %7, %163 : tile<i32>
    %165 = cmpf greater_than_or_equal unordered %15, %20 : tile<128xf64> -> tile<128xi1>
    %166 = exti %165 unsigned : tile<128xi1> -> tile<128xi32>
    %167 = itof %166 signed rounding<nearest_even> : tile<128xi32> -> tile<128xf64>
    %168 = reshape %164 : tile<i32> -> tile<1xi32>
    %169 = broadcast %168 : tile<1xi32> -> tile<128xi32>
    %170 = iota : tile<128xi32>
    %171 = addi %169, %170 : tile<128xi32>
    %172 = reshape %arg2 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %173 = broadcast %172 : tile<1xptr<f64>> -> tile<128xptr<f64>>
    %174 = offset %173, %171 : tile<128xptr<f64>>, tile<128xi32> -> tile<128xptr<f64>>
    %175 = store_ptr_tko weak %174, %167 token=%162 : tile<128xptr<f64>>, tile<128xf64> -> token
    %176 = constant <i32: 1536> : tile<i32>
    %177 = addi %7, %176 : tile<i32>
    %178 = maxf %15, %20 : tile<128xf64>
    %179 = reshape %177 : tile<i32> -> tile<1xi32>
    %180 = broadcast %179 : tile<1xi32> -> tile<128xi32>
    %181 = iota : tile<128xi32>
    %182 = addi %180, %181 : tile<128xi32>
    %183 = reshape %arg2 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %184 = broadcast %183 : tile<1xptr<f64>> -> tile<128xptr<f64>>
    %185 = offset %184, %182 : tile<128xptr<f64>>, tile<128xi32> -> tile<128xptr<f64>>
    %186 = store_ptr_tko weak %185, %178 token=%175 : tile<128xptr<f64>>, tile<128xf64> -> token
    %187 = constant <i32: 1664> : tile<i32>
    %188 = addi %7, %187 : tile<i32>
    %189 = maxf %15, %20 propagate_nan : tile<128xf64>
    %190 = reshape %188 : tile<i32> -> tile<1xi32>
    %191 = broadcast %190 : tile<1xi32> -> tile<128xi32>
    %192 = iota : tile<128xi32>
    %193 = addi %191, %192 : tile<128xi32>
    %194 = reshape %arg2 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %195 = broadcast %194 : tile<1xptr<f64>> -> tile<128xptr<f64>>
    %196 = offset %195, %193 : tile<128xptr<f64>>, tile<128xi32> -> tile<128xptr<f64>>
    %197 = store_ptr_tko weak %196, %189 token=%186 : tile<128xptr<f64>>, tile<128xf64> -> token
    %198 = constant <i32: 1792> : tile<i32>
    %199 = addi %7, %198 : tile<i32>
    %200 = minf %15, %20 : tile<128xf64>
    %201 = reshape %199 : tile<i32> -> tile<1xi32>
    %202 = broadcast %201 : tile<1xi32> -> tile<128xi32>
    %203 = iota : tile<128xi32>
    %204 = addi %202, %203 : tile<128xi32>
    %205 = reshape %arg2 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %206 = broadcast %205 : tile<1xptr<f64>> -> tile<128xptr<f64>>
    %207 = offset %206, %204 : tile<128xptr<f64>>, tile<128xi32> -> tile<128xptr<f64>>
    %208 = store_ptr_tko weak %207, %200 token=%197 : tile<128xptr<f64>>, tile<128xf64> -> token
    %209 = constant <i32: 1920> : tile<i32>
    %210 = addi %7, %209 : tile<i32>
    %211 = minf %15, %20 propagate_nan : tile<128xf64>
    %212 = reshape %210 : tile<i32> -> tile<1xi32>
    %213 = broadcast %212 : tile<1xi32> -> tile<128xi32>
    %214 = iota : tile<128xi32>
    %215 = addi %213, %214 : tile<128xi32>
    %216 = reshape %arg2 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %217 = broadcast %216 : tile<1xptr<f64>> -> tile<128xptr<f64>>
    %218 = offset %217, %215 : tile<128xptr<f64>>, tile<128xi32> -> tile<128xptr<f64>>
    %219 = store_ptr_tko weak %218, %211 token=%208 : tile<128xptr<f64>>, tile<128xf64> -> token
    return
  }
}
