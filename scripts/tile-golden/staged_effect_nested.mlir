cuda_tile.module @m {
  entry @staged_effect_nested(%arg0: tile<ptr<f64>>, %arg1: tile<ptr<f64>>) {
    %0 = make_token : token
    %1, %2, %3 = get_tile_block_id : tile<i32>
    %4 = constant <i32: 128> : tile<i32>
    %5 = muli %1, %4 : tile<i32>
    %6 = assume div_by<16>, %arg0 : tile<ptr<f64>>
    %7 = make_tensor_view %6, shape = [512], strides = [1] : tensor_view<512xf64, strides=[1]>
    %8 = make_partition_view %7 : partition_view<tile=(128), padding_value = zero, tensor_view<512xf64, strides=[1]>, dim_map=[0]>
    %9, %10, %11 = get_tile_block_id : tile<i32>
    %12, %13 = load_view_tko weak %8[%9] token=%0 : partition_view<tile=(128), padding_value = zero, tensor_view<512xf64, strides=[1]>, dim_map=[0]>, tile<i32> -> tile<128xf64>, token
    %14 = constant <i32: 0> : tile<i32>
    %15 = reshape %14 : tile<i32> -> tile<1xi32>
    %16 = broadcast %15 : tile<1xi32> -> tile<1xi32>
    %17 = iota : tile<1xi32>
    %18 = addi %16, %17 : tile<1xi32>
    %19 = reshape %arg0 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %20 = broadcast %19 : tile<1xptr<f64>> -> tile<1xptr<f64>>
    %21 = offset %20, %18 : tile<1xptr<f64>>, tile<1xi32> -> tile<1xptr<f64>>
    %22, %23 = load_ptr_tko weak %21 token=%0 : tile<1xptr<f64>> -> tile<1xf64>, token
    %24 = reduce %22 dim=0 identities=[0.0 : f64] : tile<1xf64> -> tile<f64> (%25: tile<f64>, %26: tile<f64>) {
      %27 = addf %25, %26 rounding<nearest_even> : tile<f64>
      yield %27 : tile<f64>
    }
    %28 = constant <f64: 0.0> : tile<f64>
    %29 = cmpf less_than ordered %24, %28 : tile<f64> -> tile<i1>
    %30 = if %29 -> (token) {
      %31, %32, %33 = get_tile_block_id : tile<i32>
      %34 = constant <i32: 2> : tile<i32>
      %35 = cmpi less_than %31, %34, signed : tile<i32> -> tile<i1>
      %36 = if %35 -> (token) {
        %37 = constant <f64: 13.0> : tile<128xf64>
        %38 = addf %12, %37 rounding<nearest_even> : tile<128xf64>
        %39 = reshape %5 : tile<i32> -> tile<1xi32>
        %40 = broadcast %39 : tile<1xi32> -> tile<128xi32>
        %41 = iota : tile<128xi32>
        %42 = addi %40, %41 : tile<128xi32>
        %43 = reshape %arg1 : tile<ptr<f64>> -> tile<1xptr<f64>>
        %44 = broadcast %43 : tile<1xptr<f64>> -> tile<128xptr<f64>>
        %45 = offset %44, %42 : tile<128xptr<f64>>, tile<128xi32> -> tile<128xptr<f64>>
        %46 = store_ptr_tko weak %45, %38 token=%0 : tile<128xptr<f64>>, tile<128xf64> -> token
        yield %46 : token
      } else {
        %47 = constant <f64: 17.0> : tile<128xf64>
        %48 = subf %12, %47 rounding<nearest_even> : tile<128xf64>
        %49 = reshape %5 : tile<i32> -> tile<1xi32>
        %50 = broadcast %49 : tile<1xi32> -> tile<128xi32>
        %51 = iota : tile<128xi32>
        %52 = addi %50, %51 : tile<128xi32>
        %53 = reshape %arg1 : tile<ptr<f64>> -> tile<1xptr<f64>>
        %54 = broadcast %53 : tile<1xptr<f64>> -> tile<128xptr<f64>>
        %55 = offset %54, %52 : tile<128xptr<f64>>, tile<128xi32> -> tile<128xptr<f64>>
        %56 = store_ptr_tko weak %55, %48 token=%0 : tile<128xptr<f64>>, tile<128xf64> -> token
        yield %56 : token
      }
      yield %36 : token
    } else {
      %57 = constant <f64: 3.0> : tile<128xf64>
      %58 = mulf %12, %57 rounding<nearest_even> : tile<128xf64>
      %59 = reshape %5 : tile<i32> -> tile<1xi32>
      %60 = broadcast %59 : tile<1xi32> -> tile<128xi32>
      %61 = iota : tile<128xi32>
      %62 = addi %60, %61 : tile<128xi32>
      %63 = reshape %arg1 : tile<ptr<f64>> -> tile<1xptr<f64>>
      %64 = broadcast %63 : tile<1xptr<f64>> -> tile<128xptr<f64>>
      %65 = offset %64, %62 : tile<128xptr<f64>>, tile<128xi32> -> tile<128xptr<f64>>
      %66 = store_ptr_tko weak %65, %58 token=%0 : tile<128xptr<f64>>, tile<128xf64> -> token
      %67, %68, %69 = get_tile_block_id : tile<i32>
      %70 = constant <i32: 0> : tile<i32>
      %71 = cmpi equal %67, %70, signed : tile<i32> -> tile<i1>
      %72, %73 = if %71 -> (tile<128xf64>, token) {
        %74, %75 = load_ptr_tko weak %65 token=%66 : tile<128xptr<f64>> -> tile<128xf64>, token
        yield %74, %75 : tile<128xf64>, token
      } else {
        %76, %77 = load_ptr_tko weak %65 token=%66 : tile<128xptr<f64>> -> tile<128xf64>, token
        %78 = constant <f64: 19.0> : tile<128xf64>
        %79 = addf %76, %78 rounding<nearest_even> : tile<128xf64>
        yield %79, %77 : tile<128xf64>, token
      }
      %80 = store_ptr_tko weak %65, %72 token=%73 : tile<128xptr<f64>>, tile<128xf64> -> token
      yield %80 : token
    }
    %81 = reshape %5 : tile<i32> -> tile<1xi32>
    %82 = broadcast %81 : tile<1xi32> -> tile<128xi32>
    %83 = iota : tile<128xi32>
    %84 = addi %82, %83 : tile<128xi32>
    %85 = reshape %arg1 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %86 = broadcast %85 : tile<1xptr<f64>> -> tile<128xptr<f64>>
    %87 = offset %86, %84 : tile<128xptr<f64>>, tile<128xi32> -> tile<128xptr<f64>>
    %88, %89 = load_ptr_tko weak %87 token=%30 : tile<128xptr<f64>> -> tile<128xf64>, token
    %90 = constant <f64: 1.0> : tile<128xf64>
    %91 = addf %88, %90 rounding<nearest_even> : tile<128xf64>
    %92 = store_ptr_tko weak %87, %91 token=%89 : tile<128xptr<f64>>, tile<128xf64> -> token
    return
  }
}
