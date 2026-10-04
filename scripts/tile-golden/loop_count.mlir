cuda_tile.module @m {
  entry @loop_count(%arg0: tile<ptr<i32>>, %arg1: tile<ptr<i32>>) {
    %0 = make_token : token
    %1 = constant <i32: 0> : tile<128xi32>
    %2 = assume div_by<16>, %arg0 : tile<ptr<i32>>
    %3 = make_tensor_view %2, shape = [128], strides = [1] : tensor_view<128xi32, strides=[1]>
    %4 = make_partition_view %3 : partition_view<tile=(128), padding_value = zero, tensor_view<128xi32, strides=[1]>, dim_map=[0]>
    %5, %6, %7 = get_tile_block_id : tile<i32>
    %8, %9 = load_view_tko weak %4[%5] token=%0 : partition_view<tile=(128), padding_value = zero, tensor_view<128xi32, strides=[1]>, dim_map=[0]>, tile<i32> -> tile<128xi32>, token
    %10, %11, %12 = loop iter_values(%13 = %8, %14 = %1, %15 = %9) : tile<128xi32>, tile<128xi32>, token -> (tile<128xi32>, tile<128xi32>, token) {
      %16 = reduce %13 dim=0 identities=[1 : i32] : tile<128xi32> -> tile<i32> (%17: tile<i32>, %18: tile<i32>) {
        %19 = maxi %17, %18 signed : tile<i32>
        yield %19 : tile<i32>
      }
      %20 = constant <i32: 1> : tile<i32>
      %21 = cmpi less_than_or_equal %16, %20, signed : tile<i32> -> tile<i1>
      %22 = constant <i32: 1> : tile<128xi32>
      %23 = cmpi less_than %22, %13, signed : tile<128xi32> -> tile<128xi1>
      %24 = constant <i32: 2> : tile<128xi32>
      %25 = remi %13, %24 signed : tile<128xi32>
      %26 = constant <i32: 0> : tile<128xi32>
      %27 = cmpi equal %25, %26, signed : tile<128xi32> -> tile<128xi1>
      %28 = divi %13, %24 signed : tile<128xi32>
      %29 = constant <i32: 3> : tile<128xi32>
      %30 = muli %13, %29 : tile<128xi32>
      %31 = addi %30, %22 : tile<128xi32>
      %32 = select %27, %28, %31 : tile<128xi1>, tile<128xi32>
      %33 = select %23, %32, %13 : tile<128xi1>, tile<128xi32>
      %34 = select %23, %22, %26 : tile<128xi1>, tile<128xi32>
      %35 = addi %14, %34 : tile<128xi32>
      if %21 {
        break %13, %14, %15 : tile<128xi32>, tile<128xi32>, token
      } else {
        yield
      }
      continue %33, %35, %15 : tile<128xi32>, tile<128xi32>, token
    }
    %36 = reduce %11 dim=0 identities=[0 : i32] : tile<128xi32> -> tile<i32> (%37: tile<i32>, %38: tile<i32>) {
      %39 = maxi %37, %38 signed : tile<i32>
      yield %39 : tile<i32>
    }
    %40 = assume div_by<16>, %arg1 : tile<ptr<i32>>
    %41 = make_tensor_view %40, shape = [256], strides = [1] : tensor_view<256xi32, strides=[1]>
    %42 = make_partition_view %41 : partition_view<tile=(128), padding_value = zero, tensor_view<256xi32, strides=[1]>, dim_map=[0]>
    %43 = constant <i32: 2> : tile<i32>
    %44 = muli %5, %43 : tile<i32>
    %45 = store_view_tko weak %11, %42[%44] token=%12 : tile<128xi32>, partition_view<tile=(128), padding_value = zero, tensor_view<256xi32, strides=[1]>, dim_map=[0]>, tile<i32> -> token
    %46 = reshape %36 : tile<i32> -> tile<1xi32>
    %47 = broadcast %46 : tile<1xi32> -> tile<128xi32>
    %48 = constant <i32: 2> : tile<i32>
    %49 = muli %5, %48 : tile<i32>
    %50 = constant <i32: 1> : tile<i32>
    %51 = addi %49, %50 : tile<i32>
    %52 = store_view_tko weak %47, %42[%51] token=%45 : tile<128xi32>, partition_view<tile=(128), padding_value = zero, tensor_view<256xi32, strides=[1]>, dim_map=[0]>, tile<i32> -> token
    return
  }
}
