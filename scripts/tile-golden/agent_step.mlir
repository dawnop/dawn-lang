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
    %105 = select %98, %52, %99 : tile<64xi1>, tile<64xf64>
    %106 = reduce %105 dim=0 identities=[0.0 : f64] : tile<64xf64> -> tile<f64> (%107: tile<f64>, %108: tile<f64>) {
      %109 = addf %107, %108 rounding<nearest_even> : tile<f64>
      yield %109 : tile<f64>
    }
    %110 = constant <f64: 1.0> : tile<64xf64>
    %111 = select %98, %110, %99 : tile<64xi1>, tile<64xf64>
    %112 = reduce %111 dim=0 identities=[0.0 : f64] : tile<64xf64> -> tile<f64> (%113: tile<f64>, %114: tile<f64>) {
      %115 = addf %113, %114 rounding<nearest_even> : tile<f64>
      yield %115 : tile<f64>
    }
    %116 = constant <f64: 0.0> : tile<f64>
    %117 = cmpf greater_than ordered %112, %116 : tile<f64> -> tile<i1>
    %118 = constant <f64: 1.0> : tile<f64>
    %119 = select %117, %112, %118 : tile<i1>, tile<f64>
    %120 = reshape %5 : tile<i32> -> tile<1xi32>
    %121 = broadcast %120 : tile<1xi32> -> tile<1xi32>
    %122 = iota : tile<1xi32>
    %123 = constant <i32: 0> : tile<1xi32>
    %124 = muli %122, %123 : tile<1xi32>
    %125 = addi %121, %124 : tile<1xi32>
    %126 = reshape %arg0 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %127 = broadcast %126 : tile<1xptr<f64>> -> tile<1xptr<f64>>
    %128 = offset %127, %125 : tile<1xptr<f64>>, tile<1xi32> -> tile<1xptr<f64>>
    %129, %130 = load_ptr_tko weak %128 token=%77 : tile<1xptr<f64>> -> tile<1xf64>, token
    %131 = constant <i32: 1> : tile<i32>
    %132 = addi %5, %131 : tile<i32>
    %133 = reshape %132 : tile<i32> -> tile<1xi32>
    %134 = broadcast %133 : tile<1xi32> -> tile<1xi32>
    %135 = iota : tile<1xi32>
    %136 = constant <i32: 0> : tile<1xi32>
    %137 = muli %135, %136 : tile<1xi32>
    %138 = addi %134, %137 : tile<1xi32>
    %139 = reshape %arg0 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %140 = broadcast %139 : tile<1xptr<f64>> -> tile<1xptr<f64>>
    %141 = offset %140, %138 : tile<1xptr<f64>>, tile<1xi32> -> tile<1xptr<f64>>
    %142, %143 = load_ptr_tko weak %141 token=%130 : tile<1xptr<f64>> -> tile<1xf64>, token
    %144 = constant <i32: 2> : tile<i32>
    %145 = addi %5, %144 : tile<i32>
    %146 = reshape %145 : tile<i32> -> tile<1xi32>
    %147 = broadcast %146 : tile<1xi32> -> tile<1xi32>
    %148 = iota : tile<1xi32>
    %149 = constant <i32: 0> : tile<1xi32>
    %150 = muli %148, %149 : tile<1xi32>
    %151 = addi %147, %150 : tile<1xi32>
    %152 = reshape %arg0 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %153 = broadcast %152 : tile<1xptr<f64>> -> tile<1xptr<f64>>
    %154 = offset %153, %151 : tile<1xptr<f64>>, tile<1xi32> -> tile<1xptr<f64>>
    %155, %156 = load_ptr_tko weak %154 token=%143 : tile<1xptr<f64>> -> tile<1xf64>, token
    %157 = constant <i32: 3> : tile<i32>
    %158 = addi %5, %157 : tile<i32>
    %159 = reshape %158 : tile<i32> -> tile<1xi32>
    %160 = broadcast %159 : tile<1xi32> -> tile<1xi32>
    %161 = iota : tile<1xi32>
    %162 = constant <i32: 0> : tile<1xi32>
    %163 = muli %161, %162 : tile<1xi32>
    %164 = addi %160, %163 : tile<1xi32>
    %165 = reshape %arg0 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %166 = broadcast %165 : tile<1xptr<f64>> -> tile<1xptr<f64>>
    %167 = offset %166, %164 : tile<1xptr<f64>>, tile<1xi32> -> tile<1xptr<f64>>
    %168, %169 = load_ptr_tko weak %167 token=%156 : tile<1xptr<f64>> -> tile<1xf64>, token
    %170 = divf %101, %119 rounding<nearest_even> : tile<f64>
    %171 = reshape %117 : tile<i1> -> tile<1xi1>
    %172 = broadcast %171 : tile<1xi1> -> tile<1xi1>
    %173 = reshape %170 : tile<f64> -> tile<1xf64>
    %174 = broadcast %173 : tile<1xf64> -> tile<1xf64>
    %175 = select %172, %174, %155 : tile<1xi1>, tile<1xf64>
    %176 = divf %106, %119 rounding<nearest_even> : tile<f64>
    %177 = reshape %176 : tile<f64> -> tile<1xf64>
    %178 = broadcast %177 : tile<1xf64> -> tile<1xf64>
    %179 = select %172, %178, %168 : tile<1xi1>, tile<1xf64>
    %180 = subf %175, %155 rounding<nearest_even> : tile<1xf64>
    %181 = constant <f64: 0.05> : tile<1xf64>
    %182 = mulf %181, %180 rounding<nearest_even> : tile<1xf64>
    %183 = addf %155, %182 rounding<nearest_even> : tile<1xf64>
    %184 = subf %179, %168 rounding<nearest_even> : tile<1xf64>
    %185 = mulf %181, %184 rounding<nearest_even> : tile<1xf64>
    %186 = addf %168, %185 rounding<nearest_even> : tile<1xf64>
    %187 = addf %129, %183 rounding<nearest_even> : tile<1xf64>
    %188 = assume div_by<16>, %arg1 : tile<ptr<f64>>
    %189 = make_tensor_view %188, shape = [256], strides = [1] : tensor_view<256xf64, strides=[1]>
    %190 = make_partition_view %189 : partition_view<tile=(1), padding_value = zero, tensor_view<256xf64, strides=[1]>, dim_map=[0]>
    %191, %192, %193 = get_tile_block_id : tile<i32>
    %194 = constant <i32: 4> : tile<i32>
    %195 = muli %191, %194 : tile<i32>
    %196 = store_view_tko weak %187, %190[%195] token=%169 : tile<1xf64>, partition_view<tile=(1), padding_value = zero, tensor_view<256xf64, strides=[1]>, dim_map=[0]>, tile<i32> -> token
    %197 = addf %142, %186 rounding<nearest_even> : tile<1xf64>
    %198 = constant <i32: 4> : tile<i32>
    %199 = muli %191, %198 : tile<i32>
    %200 = constant <i32: 1> : tile<i32>
    %201 = addi %199, %200 : tile<i32>
    %202 = store_view_tko weak %197, %190[%201] token=%196 : tile<1xf64>, partition_view<tile=(1), padding_value = zero, tensor_view<256xf64, strides=[1]>, dim_map=[0]>, tile<i32> -> token
    %203 = constant <i32: 4> : tile<i32>
    %204 = muli %191, %203 : tile<i32>
    %205 = constant <i32: 2> : tile<i32>
    %206 = addi %204, %205 : tile<i32>
    %207 = store_view_tko weak %183, %190[%206] token=%202 : tile<1xf64>, partition_view<tile=(1), padding_value = zero, tensor_view<256xf64, strides=[1]>, dim_map=[0]>, tile<i32> -> token
    %208 = constant <i32: 4> : tile<i32>
    %209 = muli %191, %208 : tile<i32>
    %210 = constant <i32: 3> : tile<i32>
    %211 = addi %209, %210 : tile<i32>
    %212 = store_view_tko weak %186, %190[%211] token=%207 : tile<1xf64>, partition_view<tile=(1), padding_value = zero, tensor_view<256xf64, strides=[1]>, dim_map=[0]>, tile<i32> -> token
    return
  }
}
