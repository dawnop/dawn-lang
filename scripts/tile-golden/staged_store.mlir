cuda_tile.module @m {
  entry @staged_store(%arg0: tile<ptr<f64>>, %arg1: tile<ptr<f64>>) {
    %0 = make_token : token
    %1 = assume div_by<16>, %arg0 : tile<ptr<f64>>
    %2 = make_tensor_view %1, shape = [512], strides = [1] : tensor_view<512xf64, strides=[1]>
    %3 = make_partition_view %2 : partition_view<tile=(128), padding_value = zero, tensor_view<512xf64, strides=[1]>, dim_map=[0]>
    %4, %5, %6 = get_tile_block_id : tile<i32>
    %7, %8 = load_view_tko weak %3[%4] token=%0 : partition_view<tile=(128), padding_value = zero, tensor_view<512xf64, strides=[1]>, dim_map=[0]>, tile<i32> -> tile<128xf64>, token
    %9, %10, %11 = get_tile_block_id : tile<i32>
    %12 = constant <i32: 128> : tile<i32>
    %13 = muli %9, %12 : tile<i32>
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
      %31 = constant <f64: 5.0> : tile<128xf64>
      %32 = addf %7, %31 rounding<nearest_even> : tile<128xf64>
      %33 = reshape %13 : tile<i32> -> tile<1xi32>
      %34 = broadcast %33 : tile<1xi32> -> tile<128xi32>
      %35 = iota : tile<128xi32>
      %36 = addi %34, %35 : tile<128xi32>
      %37 = reshape %arg1 : tile<ptr<f64>> -> tile<1xptr<f64>>
      %38 = broadcast %37 : tile<1xptr<f64>> -> tile<128xptr<f64>>
      %39 = offset %38, %36 : tile<128xptr<f64>>, tile<128xi32> -> tile<128xptr<f64>>
      %40 = store_ptr_tko weak %39, %32 token=%0 : tile<128xptr<f64>>, tile<128xf64> -> token
      yield %40 : token
    } else {
      %41 = constant <f64: 7.0> : tile<128xf64>
      %42 = subf %7, %41 rounding<nearest_even> : tile<128xf64>
      %43 = reshape %13 : tile<i32> -> tile<1xi32>
      %44 = broadcast %43 : tile<1xi32> -> tile<128xi32>
      %45 = iota : tile<128xi32>
      %46 = addi %44, %45 : tile<128xi32>
      %47 = reshape %arg1 : tile<ptr<f64>> -> tile<1xptr<f64>>
      %48 = broadcast %47 : tile<1xptr<f64>> -> tile<128xptr<f64>>
      %49 = offset %48, %46 : tile<128xptr<f64>>, tile<128xi32> -> tile<128xptr<f64>>
      %50 = store_ptr_tko weak %49, %42 token=%0 : tile<128xptr<f64>>, tile<128xf64> -> token
      yield %50 : token
    }
    %51 = reshape %13 : tile<i32> -> tile<1xi32>
    %52 = broadcast %51 : tile<1xi32> -> tile<128xi32>
    %53 = iota : tile<128xi32>
    %54 = addi %52, %53 : tile<128xi32>
    %55 = reshape %arg1 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %56 = broadcast %55 : tile<1xptr<f64>> -> tile<128xptr<f64>>
    %57 = offset %56, %54 : tile<128xptr<f64>>, tile<128xi32> -> tile<128xptr<f64>>
    %58, %59 = load_ptr_tko weak %57 token=%30 : tile<128xptr<f64>> -> tile<128xf64>, token
    %60 = constant <f64: 2.0> : tile<128xf64>
    %61 = mulf %58, %60 rounding<nearest_even> : tile<128xf64>
    %62 = store_ptr_tko weak %57, %61 token=%59 : tile<128xptr<f64>>, tile<128xf64> -> token
    return
  }
}
