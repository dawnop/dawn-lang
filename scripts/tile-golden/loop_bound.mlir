cuda_tile.module @m {
  entry @loop_bound(%arg0: tile<ptr<i32>>, %arg1: tile<ptr<i32>>) {
    %0 = make_token : token
    %1 = constant <i32: 0> : tile<128xi32>
    %2 = assume div_by<16>, %arg0 : tile<ptr<i32>>
    %3 = make_tensor_view %2, shape = [128], strides = [1] : tensor_view<128xi32, strides=[1]>
    %4 = make_partition_view %3 : partition_view<tile=(128), padding_value = zero, tensor_view<128xi32, strides=[1]>, dim_map=[0]>
    %5, %6, %7 = get_tile_block_id : tile<i32>
    %8, %9 = load_view_tko weak %4[%5] token=%0 : partition_view<tile=(128), padding_value = zero, tensor_view<128xi32, strides=[1]>, dim_map=[0]>, tile<i32> -> tile<128xi32>, token
    %10 = constant <i32: 0> : tile<i32>
    %11 = constant <i32: 128> : tile<i32>
    %12 = constant <i32: 1> : tile<i32>
    %13, %14, %15 = for %16 in (%10 to %11, step %12) : tile<i32> iter_values(%17 = %8, %18 = %1, %19 = %9) -> (tile<128xi32>, tile<128xi32>, token) {
      %20 = constant <i32: 1> : tile<128xi32>
      %21 = cmpi less_than %20, %17, signed : tile<128xi32> -> tile<128xi1>
      %22 = constant <i32: 2> : tile<128xi32>
      %23 = remi %17, %22 signed : tile<128xi32>
      %24 = constant <i32: 0> : tile<128xi32>
      %25 = cmpi equal %23, %24, signed : tile<128xi32> -> tile<128xi1>
      %26 = divi %17, %22 signed : tile<128xi32>
      %27 = constant <i32: 3> : tile<128xi32>
      %28 = muli %17, %27 : tile<128xi32>
      %29 = addi %28, %20 : tile<128xi32>
      %30 = select %25, %26, %29 : tile<128xi1>, tile<128xi32>
      %31 = select %21, %30, %17 : tile<128xi1>, tile<128xi32>
      %32 = select %21, %20, %24 : tile<128xi1>, tile<128xi32>
      %33 = addi %18, %32 : tile<128xi32>
      continue %31, %33, %19 : tile<128xi32>, tile<128xi32>, token
    }
    %34 = assume div_by<16>, %arg1 : tile<ptr<i32>>
    %35 = make_tensor_view %34, shape = [128], strides = [1] : tensor_view<128xi32, strides=[1]>
    %36 = make_partition_view %35 : partition_view<tile=(128), padding_value = zero, tensor_view<128xi32, strides=[1]>, dim_map=[0]>
    %37 = store_view_tko weak %14, %36[%5] token=%15 : tile<128xi32>, partition_view<tile=(128), padding_value = zero, tensor_view<128xi32, strides=[1]>, dim_map=[0]>, tile<i32> -> token
    return
  }
}
