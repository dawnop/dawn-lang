cuda_tile.module @m {
  entry @staged_load(%arg0: tile<ptr<f64>>, %arg1: tile<ptr<f64>>) {
    %0 = make_token : token
    %1 = constant <i32: 0> : tile<i32>
    %2 = reshape %1 : tile<i32> -> tile<1xi32>
    %3 = broadcast %2 : tile<1xi32> -> tile<1xi32>
    %4 = iota : tile<1xi32>
    %5 = addi %3, %4 : tile<1xi32>
    %6 = reshape %arg0 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %7 = broadcast %6 : tile<1xptr<f64>> -> tile<1xptr<f64>>
    %8 = offset %7, %5 : tile<1xptr<f64>>, tile<1xi32> -> tile<1xptr<f64>>
    %9, %10 = load_ptr_tko weak %8 token=%0 : tile<1xptr<f64>> -> tile<1xf64>, token
    %11 = reduce %9 dim=0 identities=[0.0 : f64] : tile<1xf64> -> tile<f64> (%12: tile<f64>, %13: tile<f64>) {
      %14 = addf %12, %13 rounding<nearest_even> : tile<f64>
      yield %14 : tile<f64>
    }
    %15 = constant <f64: 0.0> : tile<f64>
    %16 = cmpf less_than ordered %11, %15 : tile<f64> -> tile<i1>
    %17 = if %16 -> (tile<128xf64>) {
      %18 = assume div_by<16>, %arg0 : tile<ptr<f64>>
      %19 = make_tensor_view %18, shape = [512], strides = [1] : tensor_view<512xf64, strides=[1]>
      %20 = make_partition_view %19 : partition_view<tile=(128), padding_value = zero, tensor_view<512xf64, strides=[1]>, dim_map=[0]>
      %21, %22, %23 = get_tile_block_id : tile<i32>
      %24, %25 = load_view_tko weak %20[%21] token=%0 : partition_view<tile=(128), padding_value = zero, tensor_view<512xf64, strides=[1]>, dim_map=[0]>, tile<i32> -> tile<128xf64>, token
      %26 = constant <f64: 2.0> : tile<128xf64>
      %27 = addf %24, %26 rounding<nearest_even> : tile<128xf64>
      yield %27 : tile<128xf64>
    } else {
      %28 = assume div_by<16>, %arg0 : tile<ptr<f64>>
      %29 = make_tensor_view %28, shape = [512], strides = [1] : tensor_view<512xf64, strides=[1]>
      %30 = make_partition_view %29 : partition_view<tile=(128), padding_value = zero, tensor_view<512xf64, strides=[1]>, dim_map=[0]>
      %31, %32, %33 = get_tile_block_id : tile<i32>
      %34, %35 = load_view_tko weak %30[%31] token=%0 : partition_view<tile=(128), padding_value = zero, tensor_view<512xf64, strides=[1]>, dim_map=[0]>, tile<i32> -> tile<128xf64>, token
      %36 = constant <f64: 3.0> : tile<128xf64>
      %37 = subf %34, %36 rounding<nearest_even> : tile<128xf64>
      yield %37 : tile<128xf64>
    }
    %38, %39, %40 = get_tile_block_id : tile<i32>
    %41 = constant <i32: 128> : tile<i32>
    %42 = muli %38, %41 : tile<i32>
    %43 = reshape %42 : tile<i32> -> tile<1xi32>
    %44 = broadcast %43 : tile<1xi32> -> tile<128xi32>
    %45 = iota : tile<128xi32>
    %46 = addi %44, %45 : tile<128xi32>
    %47 = reshape %arg1 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %48 = broadcast %47 : tile<1xptr<f64>> -> tile<128xptr<f64>>
    %49 = offset %48, %46 : tile<128xptr<f64>>, tile<128xi32> -> tile<128xptr<f64>>
    %50 = store_ptr_tko weak %49, %17 token=%0 : tile<128xptr<f64>>, tile<128xf64> -> token
    return
  }
}
