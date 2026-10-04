cuda_tile.module @m {
  entry @attr_sat(%arg0: tile<ptr<f64>>, %arg1: tile<ptr<i32>>) {
    %0 = make_token : token
    %1, %2, %3 = get_tile_block_id : tile<i32>
    %4 = constant <i32: 128> : tile<i32>
    %5 = muli %1, %4 : tile<i32>
    %6 = constant <i32: 256> : tile<i32>
    %7 = muli %1, %6 : tile<i32>
    %8, %9, %10 = get_num_tile_blocks : tile<i32>
    %11 = constant <i32: 128> : tile<i32>
    %12 = muli %8, %11 : tile<i32>
    %13 = assume div_by<16>, %arg0 : tile<ptr<f64>>
    %14 = make_tensor_view %13, shape = [%12], strides = [1] : tile<i32> -> tensor_view<?xf64, strides=[1]>
    %15 = make_partition_view %14 : partition_view<tile=(128), padding_value = zero, tensor_view<?xf64, strides=[1]>, dim_map=[0]>
    %16, %17, %18 = get_tile_block_id : tile<i32>
    %19, %20 = load_view_tko weak %15[%16] token=%0 : partition_view<tile=(128), padding_value = zero, tensor_view<?xf64, strides=[1]>, dim_map=[0]>, tile<i32> -> tile<128xf64>, token
    %21 = constant <f64: -2.147483649E9> : tile<128xf64>
    %22 = cmpf greater_than ordered %19, %21 : tile<128xf64> -> tile<128xi1>
    %23 = constant <f64: 2.147483648E9> : tile<128xf64>
    %24 = cmpf less_than ordered %19, %23 : tile<128xf64> -> tile<128xi1>
    %25 = constant <i1: 0> : tile<128xi1>
    %26 = select %22, %24, %25 : tile<128xi1>, tile<128xi1>
    %27 = ftoi %19 signed rounding<nearest_int_to_zero> saturating : tile<128xf64> -> tile<128xi32>
    %28 = reshape %7 : tile<i32> -> tile<1xi32>
    %29 = broadcast %28 : tile<1xi32> -> tile<128xi32>
    %30 = iota : tile<128xi32>
    %31 = addi %29, %30 : tile<128xi32>
    %32 = reshape %arg1 : tile<ptr<i32>> -> tile<1xptr<i32>>
    %33 = broadcast %32 : tile<1xptr<i32>> -> tile<128xptr<i32>>
    %34 = offset %33, %31 : tile<128xptr<i32>>, tile<128xi32> -> tile<128xptr<i32>>
    %35 = store_ptr_tko weak %34, %27 token=%20 : tile<128xptr<i32>>, tile<128xi32> -> token
    %36 = constant <i32: 128> : tile<i32>
    %37 = addi %7, %36 : tile<i32>
    %38 = ftoi %19 signed rounding<nearest_int_to_zero> : tile<128xf64> -> tile<128xi32>
    %39 = reshape %37 : tile<i32> -> tile<1xi32>
    %40 = broadcast %39 : tile<1xi32> -> tile<128xi32>
    %41 = iota : tile<128xi32>
    %42 = addi %40, %41 : tile<128xi32>
    %43 = reshape %arg1 : tile<ptr<i32>> -> tile<1xptr<i32>>
    %44 = broadcast %43 : tile<1xptr<i32>> -> tile<128xptr<i32>>
    %45 = offset %44, %42 : tile<128xptr<i32>>, tile<128xi32> -> tile<128xptr<i32>>
    %46 = store_ptr_tko weak %45, %38, %26 token=%35 : tile<128xptr<i32>>, tile<128xi32>, tile<128xi1> -> token
    return
  }
}
